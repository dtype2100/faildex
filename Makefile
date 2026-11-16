.PHONY: setup test lint data build-store eval demo

setup:
	uv sync
	git config core.hooksPath .githooks

test:
	uv run pytest -q

lint:
	uv run ruff check .

data:
	@uv run faildex sources | while read name repo rev; do \
		uvx --from huggingface_hub hf download $$repo --repo-type dataset --revision $$rev \
			--local-dir .tmp/data/$$name --quiet || exit 1; \
	done

build-store:
	uv run faildex build-store

eval:
	@echo "not implemented" && exit 1

demo:
	@echo "not implemented" && exit 1
