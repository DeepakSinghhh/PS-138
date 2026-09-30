PY ?= backend/.venv/bin/python
PIP ?= uv pip

.PHONY: install install-web test lint data train bench-quick bench-full api web dev build-web smoke demo-tts-setup demo-video

install:            ## create the backend virtualenv and install dependencies
	cd backend && uv venv .venv --python 3.11 && . .venv/bin/activate && uv pip install -r requirements.txt

install-web:        ## install frontend dependencies
	cd frontend && npm install

test:               ## run backend unit tests (fast)
	cd backend && ../$(PY) -m pytest -m "not slow"

lint:
	cd backend && .venv/bin/ruff check greenfleet tests

data:               ## build processed datasets (real files in data/raw are used when present)
	cd backend && ../$(PY) -m greenfleet.data.build

train:              ## train prediction models and the optimizer's fuel surrogate
	cd backend && ../$(PY) -m greenfleet.prediction.train

bench-quick:        ## quick prediction + optimization benchmarks (minutes)
	cd backend && ../$(PY) -m greenfleet.benchmark.run --quick

bench-full:         ## full statistical benchmarks (30 seeds, scalability sweep)
	cd backend && ../$(PY) -m greenfleet.benchmark.run --full

api:                ## start the FastAPI backend on :8000
	cd backend && ../$(PY) -m uvicorn greenfleet.api.main:app --reload --port 8000

web:                ## start the React dev server on :5173
	cd frontend && npm run dev

build-web:
	cd frontend && npm run build

smoke:              ## Playwright smoke test against running api + web
	cd frontend && npx playwright test

TTS_PY ?= tools/demo_video/.venv/bin/python
KOKORO ?= tools/demo_video/models

demo-tts-setup:     ## one-time: Kokoro TTS virtualenv + voice model (~350 MB) for the narrated demo video
	python3 -m venv tools/demo_video/.venv && $(TTS_PY) -m pip install -q kokoro-onnx soundfile
	mkdir -p $(KOKORO) && cd $(KOKORO) && for f in kokoro-v1.0.onnx voices-v1.0.bin; do [ -s $$f ] || curl -sSL -o $$f \
	  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$$f; done

demo-video:         ## record, narrate and assemble the walkthrough (needs `make api` running, ffmpeg, make demo-tts-setup)
	cd tools/demo_video && node record.js
	cd tools/demo_video && $(abspath $(TTS_PY)) narrate.py --model $(abspath $(KOKORO))
	cd tools/demo_video && ../../$(PY) assemble.py
	cp tools/demo_video/Q-GreenFleet_walkthrough.mp4 tools/demo_video/Q-GreenFleet_walkthrough.srt \
	  tools/demo_video/Q-GreenFleet_walkthrough_voiceover.md docs/demo/
