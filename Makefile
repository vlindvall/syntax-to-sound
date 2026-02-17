PYTHON ?= python3

.PHONY: venv install renardo new-song

venv:
	$(PYTHON) -m venv .venv

install:
	. .venv/bin/activate && pip install -U pip && pip install renardo

renardo:
	. .venv/bin/activate && renardo

new-song:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make new-song NAME='Neon Rain'"; \
		exit 1; \
	fi
	$(PYTHON) tools/new_song.py "$(NAME)"
