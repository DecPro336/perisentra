"""Fernbrook Market source systems, simulated.

A lot-level fresh-retail world (20 stores, 220 products) that plays out one day at a time and delivers what a
retailer's systems would: ERP, POS, WMS, waste-log, marketing, footfall and pricing extracts, dropped into an
exchange folder with a manifest per business day. Stores follow their current rule, or the daily task list a
decision system publishes for them. The world keeps its ground truth (true demand, true price response) to itself.
"""
