.PHONY: setup test lint eval demo

setup:
	uv sync
	git config core.hooksPath .githooks

test:
	uv run pytest -q

lint:
	uv run ruff check .

eval:
	@echo "not implemented" && exit 1

demo:
	@echo "not implemented" && exit 1
