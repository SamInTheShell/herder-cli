help:
	@echo "Usage: make <target>"
	@echo "Targets:"
	@echo "  build    Build the package with uv"
	@echo "  publish  Build and publish the package with uv"
	@echo "  clean    Remove build artifacts (dist/)"

build:
	uv build

publish: build
	uv publish

clean:
	rm -rf dist/ build/
	find . -name '__pycache__' -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete
	find . -name '*.pyo' -delete
	rm -rf *.egg-info

.DEFAULT_GOAL := help
