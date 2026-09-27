#!/usr/bin/env python3
"""
generate_submission.py
======================
Generates the canonical 30-line `submission.jsonl` file evaluated by the AI judge.
Loads the 30 canonical test pairs from `dataset/expanded/test_pairs.json` and
composes each using `compose()`.
"""

import json
from pathlib import Path
from composer import compose

def main():
    root_dir = Path(__file__).parent
    dataset_dir = root_dir / "dataset" / "expanded"
    test_pairs_path = dataset_dir / "test_pairs.json"
    
    if not test_pairs_path.exists():
        print(f"Error: {test_pairs_path} does not exist!")
        return

    with open(test_pairs_path) as f:
        pairs = json.load(f)["pairs"]

    print(f"Processing {len(pairs)} canonical test pairs...")

    # Load categories
    categories = {}
    for f in (dataset_dir / "categories").glob("*.json"):
        with open(f) as fp:
            data = json.load(fp)
            categories[data["slug"]] = data

    submission_lines = []

    for item in pairs:
        test_id = item["test_id"]
        trigger_id = item["trigger_id"]
        merchant_id = item["merchant_id"]
        customer_id = item.get("customer_id")

        with open(dataset_dir / "triggers" / f"{trigger_id}.json") as fp:
            trigger = json.load(fp)

        with open(dataset_dir / "merchants" / f"{merchant_id}.json") as fp:
            merchant = json.load(fp)

        cat_slug = merchant.get("category_slug")
        category = categories.get(cat_slug, {})

        customer = None
        if customer_id:
            with open(dataset_dir / "customers" / f"{customer_id}.json") as fp:
                customer = json.load(fp)

        composed = compose(category, merchant, trigger, customer)

        record = {
            "test_id": test_id,
            "body": composed["body"],
            "cta": composed["cta"],
            "send_as": composed["send_as"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"]
        }
        submission_lines.append(record)
        print(f"[{test_id}] {composed['send_as']}: {composed['body'][:60]}...")

    out_file = root_dir / "submission.jsonl"
    with open(out_file, "w") as f:
        for rec in submission_lines:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nGenerated {len(submission_lines)} lines in {out_file}")

if __name__ == "__main__":
    main()
