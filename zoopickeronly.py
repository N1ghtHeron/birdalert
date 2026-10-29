#!/usr/bin/env python3
# coding: utf-8
"""Zoopicker-only entry point using the shared login, pagination and reporting."""

from main import run_cli


if __name__ == "__main__":
    run_cli(zoopicker_only=True)
