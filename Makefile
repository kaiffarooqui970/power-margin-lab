# power-margin-lab. All targets run locally; `make test` needs no real data.
UV ?= uv
PIPE = $(UV) run python -m power_margin_lab.pipeline

.PHONY: setup download ingest build margin backtest report test lint all smoke clean-warehouse

setup:            ## install the environment (Python 3.11 via uv)
	$(UV) sync

download:         ## ECC public files (scanning ranges, margin buffer, SPAN XML) + SMARD prices
	$(PIPE) download

ingest:           ## raw files -> validated raw_* tables, quarantine, drift log
	$(PIPE) ingest

build:            ## data model: dim_product, fct_settlement, fct_tenor_series, ...
	$(PIPE) build

margin:           ## SPAN-current, SPAN-hist, FHS, SP, MRIM
	$(PIPE) margin

backtest:         ## backtests, procyclicality, diversification, validation checks
	$(PIPE) backtest

report:           ## reports/margin_comparison.md + figures + README result blocks
	$(PIPE) report

test:             ## unit tests + end-to-end smoke test on synthetic fixtures
	$(UV) run pytest -q

lint:
	$(UV) run ruff check .

smoke:
	$(UV) run pytest -q tests/test_smoke_pipeline.py

all: download ingest build margin backtest report

clean-warehouse:
	rm -f data/warehouse.duckdb
