.PHONY: quality ct-install spc-helm-docs confluence-connector-helm-docs

.DEFAULT_GOAL := quality

quality:
	@echo "Running quality checks..."
	@./scripts/lint.sh
	@echo "Quality checks completed."

ct-install:
	@ct install --config .github/configs/ct-install.yaml

spc-helm-docs:
	@services/sharepoint-connector/deploy/helm-charts/helm-docs.sh

confluence-connector-helm-docs:
	@services/confluence-connector/deploy/helm-charts/helm-docs.sh