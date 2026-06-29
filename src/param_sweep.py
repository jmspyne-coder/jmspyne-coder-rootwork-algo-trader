param-sweep:
    if: github.event_name == 'workflow_dispatch' && github.event.inputs.script == 'param_sweep'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python -m src.param_sweep --start 2024-01-01 --end 2026-06-01
      - uses: actions/upload-artifact@v4
        with:
          name: sweep-results
          path: sweep_results_*.csv
