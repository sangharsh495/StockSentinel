"""
Quant engine — trained, out-of-sample-tested models for StockSentinel.

Every probability this package publishes comes from a model that was
validated with walk-forward testing (train on the past, test on the
following unseen period, repeat). Models that fail to beat a naive
baseline are flagged with edge_verified = False so the app can say so
instead of showing a confident-looking number.
"""
