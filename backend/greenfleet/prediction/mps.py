"""Matrix Product State (tensor-train) regression: a quantum-inspired model.

Each input feature ``x_j`` (scaled to [0, 1]) is encoded as a **spin-coherent qudit state**

    phi(x)_k = sqrt(C(p, k)) * cos(pi x / 2)^(p - k) * sin(pi x / 2)^k,   k = 0..p

For ``p = 1`` this is the single-qubit encoding ``[cos, sin]`` of Stoudenmire & Schwab
(2016). With even ``p`` the basis also spans the constant function, so the model can
ignore irrelevant features. The prediction is the full contraction of the product state
of all features with an MPS weight tensor

    f(x) = A_1[phi(x_1)] A_2[phi(x_2)] ... A_n[phi(x_n)]

which represents an exponentially large (``(p+1)^n``) tensor of feature interactions with
only ``O(n (p+1) D^2)`` parameters. The bond dimension ``D`` bounds the "entanglement"
(correlation) the model can carry between feature groups.

Training uses **DMRG-style alternating least squares**: sweeping left to right and back,
every core is solved *exactly* by ridge regression while the others are held fixed, and
the gauge is moved with QR decompositions to keep the environments well conditioned.
This is the same sweep structure as the density-matrix renormalisation group used to find
ground states of quantum many-body systems.

After fitting, ``entanglement_entropy()`` returns the von Neumann entropy across each bond
(from the Schmidt / singular values in mixed-canonical form): a map of where the model
couples features.
"""

from __future__ import annotations

from math import comb

import numpy as np


class MPSRegressor:
    name = "MPS tensor network (quantum-inspired)"

    def __init__(self, bond_dim: int = 8, local_dim: int = 5, sweeps: int = 4, ridge: float = 1e-6,
                 max_train: int = 20000, seed: int = 0):
        if (local_dim - 1) % 2:
            raise ValueError("local_dim - 1 must be even so the basis contains the constant function")
        self.bond_dim, self.local_dim = bond_dim, local_dim
        self.sweeps, self.ridge, self.max_train = sweeps, ridge, max_train
        self.seed = seed
        self.cores: list[np.ndarray] = []
        self.history: list[dict] = []

    # ------------------------------------------------------------------ encoding
    def _scale(self, X: np.ndarray) -> np.ndarray:
        return np.clip((X - self.lo_) / self.span_, 0.0, 1.0)

    def encode(self, X: np.ndarray) -> np.ndarray:
        """(N, n_features) -> (N, n_features, local_dim) spin-coherent qudit states."""
        p = self.local_dim - 1
        t = self._scale(X) * np.pi / 2
        c, s = np.cos(t)[..., None], np.sin(t)[..., None]
        k = np.arange(p + 1)
        coef = np.sqrt([comb(p, int(i)) for i in k])
        return coef * c ** (p - k) * s**k

    # ------------------------------------------------------------------ contraction helpers
    @staticmethod
    def _step_left(env: np.ndarray, core: np.ndarray, phi: np.ndarray) -> np.ndarray:
        # env (N, a), core (a, s, b), phi (N, s) -> (N, b)
        return np.einsum("na,asb,ns->nb", env, core, phi, optimize=True)

    @staticmethod
    def _step_right(env: np.ndarray, core: np.ndarray, phi: np.ndarray) -> np.ndarray:
        # env (N, b), core (a, s, b), phi (N, s) -> (N, a)
        return np.einsum("nb,asb,ns->na", env, core, phi, optimize=True)

    def _solve_site(self, L: np.ndarray, phi: np.ndarray, R: np.ndarray, y: np.ndarray, shape) -> np.ndarray:
        n = len(y)
        design = np.einsum("na,ns,nb->nasb", L, phi, R, optimize=True).reshape(n, -1)
        gram = design.T @ design
        gram[np.diag_indices_from(gram)] += self.ridge * n
        w = np.linalg.solve(gram, design.T @ y)
        return w.reshape(shape)

    # ------------------------------------------------------------------ API
    def fit(self, X: np.ndarray, y: np.ndarray, X_val: np.ndarray | None = None, y_val: np.ndarray | None = None):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        rng = np.random.default_rng(self.seed)
        if len(X) > self.max_train:
            idx = rng.choice(len(X), self.max_train, replace=False)
            X, y = X[idx], y[idx]
        self.lo_ = np.nanmin(X, axis=0)
        self.span_ = np.maximum(np.nanmax(X, axis=0) - self.lo_, 1e-9)
        X = np.where(np.isnan(X), self.lo_, X)
        self.y_mean_, self.y_std_ = float(y.mean()), float(y.std() + 1e-12)
        yt = (y - self.y_mean_) / self.y_std_

        n, d, D = X.shape[1], self.local_dim, self.bond_dim
        dims = [1] + [min(D, d**i, d ** (n - i)) for i in range(1, n)] + [1]
        self.cores = [rng.normal(0, 1.0, (dims[i], d, dims[i + 1])) / np.sqrt(d * dims[i + 1]) for i in range(n)]
        # right-canonicalise so the right environments start orthonormal
        for j in range(n - 1, 0, -1):
            a, s, b = self.cores[j].shape
            q, r = np.linalg.qr(self.cores[j].reshape(a, s * b).T)
            self.cores[j] = q.T.reshape(-1, s, b)
            self.cores[j - 1] = np.einsum("asb,bc->asc", self.cores[j - 1], r.T)

        phi = self.encode(X)
        N = len(yt)
        right = [None] * (n + 1)
        right[n] = np.ones((N, 1))
        for j in range(n - 1, -1, -1):
            right[j] = self._step_right(right[j + 1], self.cores[j], phi[:, j])
        self.history = []

        for sweep in range(self.sweeps):
            # left -> right
            left = np.ones((N, 1))
            for j in range(n):
                shape = self.cores[j].shape
                core = self._solve_site(left, phi[:, j], right[j + 1], yt, shape)
                if j < n - 1:
                    a, s, b = shape
                    q, r = np.linalg.qr(core.reshape(a * s, b))
                    self.cores[j] = q.reshape(a, s, -1)
                    self.cores[j + 1] = np.einsum("ab,bsc->asc", r, self.cores[j + 1])
                    left = self._step_left(left, self.cores[j], phi[:, j])
                else:
                    self.cores[j] = core
            # right -> left
            right[n] = np.ones((N, 1))
            left_envs = [np.ones((N, 1))]
            for j in range(n - 1):
                left_envs.append(self._step_left(left_envs[-1], self.cores[j], phi[:, j]))
            for j in range(n - 1, -1, -1):
                shape = self.cores[j].shape
                core = self._solve_site(left_envs[j], phi[:, j], right[j + 1], yt, shape)
                if j > 0:
                    a, s, b = shape
                    q, r = np.linalg.qr(core.reshape(a, s * b).T)
                    self.cores[j] = q.T.reshape(-1, s, b)
                    self.cores[j - 1] = np.einsum("asb,bc->asc", self.cores[j - 1], r.T)
                    right[j] = self._step_right(right[j + 1], self.cores[j], phi[:, j])
                else:
                    self.cores[j] = core
            rec = {"sweep": sweep + 1, "train_rmse": float(np.sqrt(np.mean((self.predict(X) - y) ** 2)))}
            if X_val is not None and y_val is not None:
                rec["val_rmse"] = float(np.sqrt(np.mean((self.predict(X_val) - y_val) ** 2)))
            self.history.append(rec)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        X = np.where(np.isnan(X), self.lo_, X)
        phi = self.encode(X)
        env = np.ones((len(X), 1))
        for j, core in enumerate(self.cores):
            env = self._step_left(env, core, phi[:, j])
        return env[:, 0] * self.y_std_ + self.y_mean_

    @property
    def n_params(self) -> int:
        return int(sum(c.size for c in self.cores))

    def entanglement_entropy(self) -> list[float]:
        """Von Neumann entropy of the normalised Schmidt spectrum across each bond."""
        cores = [c.copy() for c in self.cores]
        n = len(cores)
        for j in range(n - 1):   # left-canonicalise
            a, s, b = cores[j].shape
            q, r = np.linalg.qr(cores[j].reshape(a * s, b))
            cores[j] = q.reshape(a, s, -1)
            cores[j + 1] = np.einsum("ab,bsc->asc", r, cores[j + 1])
        entropies = [0.0] * (n - 1)
        for j in range(n - 1, 0, -1):
            a, s, b = cores[j].shape
            u, sv, vt = np.linalg.svd(cores[j].reshape(a, s * b), full_matrices=False)
            cores[j] = vt.reshape(-1, s, b)
            cores[j - 1] = np.einsum("asb,bc->asc", cores[j - 1], u * sv)
            p = sv**2 / max((sv**2).sum(), 1e-300)
            p = p[p > 1e-15]
            entropies[j - 1] = float(-(p * np.log(p)).sum())
        return entropies
