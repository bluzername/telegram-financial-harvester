"""
Webhook Client - Sends parsed signals to the checklister politician webhook API.
"""

from dataclasses import asdict
from typing import Optional

import requests

from signal_parser import ParsedSignal


class WebhookClient:
    """Client for sending signals to the checklister webhook."""

    def __init__(self, webhook_url: str, api_key: str, timeout: int = 30):
        """
        Initialize the webhook client.

        Args:
            webhook_url: Full URL of the webhook endpoint
            api_key: API key for authentication
            timeout: Request timeout in seconds
        """
        self.webhook_url = webhook_url
        self.api_key = api_key
        self.timeout = timeout

    def send_signal(self, signal: ParsedSignal) -> dict:
        """
        Send a single signal to the webhook.

        Args:
            signal: ParsedSignal to send

        Returns:
            Response JSON from the webhook
        """
        payload = {
            "api_key": self.api_key,
            "ticker": signal.ticker,
            "politician_name": signal.politician_name,
            "transaction_type": signal.transaction_type,
            "amount_range": signal.amount_range,
            "signal_date": signal.signal_date,
            "source": "TELEGRAM",
            "raw_message": signal.raw_message,
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )

            return {
                "status_code": response.status_code,
                "success": response.status_code == 200,
                "response": response.json() if response.content else {},
            }
        except requests.RequestException as e:
            return {
                "status_code": 0,
                "success": False,
                "error": str(e),
            }

    def send_signals_batch(
        self, signals: list[ParsedSignal], verbose: bool = False
    ) -> dict:
        """
        Send multiple signals to the webhook.

        Args:
            signals: List of ParsedSignal objects to send
            verbose: Print progress if True

        Returns:
            Summary of results with counts
        """
        results = {
            "total": len(signals),
            "success": 0,
            "failed": 0,
            "duplicates": 0,
            "errors": [],
        }

        for i, signal in enumerate(signals):
            if verbose:
                print(f"  Sending {i + 1}/{len(signals)}: {signal.ticker}...", end=" ")

            result = self.send_signal(signal)

            if result["success"]:
                results["success"] += 1
                if verbose:
                    print("OK")
            elif result.get("status_code") == 409:
                # Duplicate signal
                results["duplicates"] += 1
                if verbose:
                    print("DUPLICATE")
            else:
                results["failed"] += 1
                error_msg = result.get("error") or result.get("response", {}).get(
                    "error", "Unknown error"
                )
                results["errors"].append(
                    {"ticker": signal.ticker, "error": error_msg}
                )
                if verbose:
                    print(f"FAILED: {error_msg}")

        return results


def send_signal(signal: ParsedSignal, api_key: str, webhook_url: str) -> dict:
    """
    Convenience function to send a single signal.

    Args:
        signal: ParsedSignal to send
        api_key: Webhook API key
        webhook_url: Webhook URL

    Returns:
        Response dict
    """
    client = WebhookClient(webhook_url, api_key)
    return client.send_signal(signal)
