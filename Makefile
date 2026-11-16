.PHONY: setup test lint data build-store eval demo site serve

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
	@uv run faildex eval

demo:
	@echo "== 1. Failures that recurred across sessions, with the recovery on record"
	@uv run faildex rules --top 5
	@echo
	@echo "== 2. Asking before running a command (what the hook and the MCP tool return)"
	@uv run faildex check "git status"
	@echo
	@echo "== 3. How often the later sessions repeated a failure the graph already held"
	@uv run faildex eval

# The browser demo: the store as JSON plus Relate WebAssembly, in site/.
site:
	@uv run faildex export-web --out site/data.json
	@mkdir -p site/vendor .tmp/npm
	@cd .tmp/npm && npm pack --silent @relate/relate-wasm@1.0.1 >/dev/null && tar -xzf relate-relate-wasm-1.0.1.tgz
	@cp .tmp/npm/package/relate.js .tmp/npm/package/relate_bg.wasm site/vendor/
	@if [ -d .tmp/npm/package/snippets ]; then cp -R .tmp/npm/package/snippets site/vendor/; fi
	@echo "site ready: run 'make serve'"

serve:
	@cd site && python3 -m http.server 8765
