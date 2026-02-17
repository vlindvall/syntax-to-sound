PYTHON ?= python3

.PHONY: venv install renardo renardo-boot renardo-prepare play live new-song

venv:
	$(PYTHON) -m venv .venv

install:
	. .venv/bin/activate && pip install -U pip && pip install renardo

renardo:
	. .venv/bin/activate && renardo

renardo-prepare:
	. .venv/bin/activate && python tools/prepare_renardo.py

renardo-boot:
	bash tools/renardo_boot.sh

play:
	@if [ -z "$(SONG)" ]; then \
		echo "Usage: make play SONG=songs/2026-02-17_boten_anna_handsup.py"; \
		exit 1; \
	fi
	SONG="$(SONG)" bash tools/renardo_boot.sh

live:
	@if [ -z "$(SONG)" ]; then \
		echo "Usage: make live SONG=songs/2026-02-17_boten_anna_handsup.py"; \
		exit 1; \
	fi
	SONG="$(SONG)" bash tools/live_play.sh

new-song:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make new-song NAME='Neon Rain'"; \
		exit 1; \
	fi
	$(PYTHON) tools/new_song.py "$(NAME)"
