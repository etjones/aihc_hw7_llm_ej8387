#!/usr/bin/env python3

import pandas as pd
import numpy as np
from pathlib import Path
import argparse
from typing import Dict, List, Optional, Union
import json


def parse_all_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for data loading.

    Args:
        args: Command line arguments. If None, sys.argv[1:] is used.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Load processed medical data for LLM analysis"
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default="data/processed",
        help="Directory containing the processed data files",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default="data/llm_input_data.txt",
        help="File to save formatted data for LLM input",
    )
    parser.add_argument(
        "--max_patients",
        type=int,
        default=50,
        help="Maximum number of patients to include in the LLM input",
    )
    parser.add_argument(
        "--max_observations",
        type=int,
        default=5,
        help="Maximum number of observations per patient to include",
    )

    return parser.parse_args(args)


def load_processed_data(data_dir: Union[str, Path]) -> Dict[str, pd.DataFrame]:
    """Load the processed data files.

    Args:
        data_dir: Directory containing the processed data files

    Returns:
        Dictionary of dataframes for each processed file
    """
    data_dir = Path(data_dir)
    required_files = [
        "patients_diabetic.csv",
        "conditions_diabetic.csv",
        "medications_diabetic.csv",
        "observation_timeline.csv",
        "medication_outcomes.csv",
    ]

    dataset = {}
    for file in required_files:
        file_path = data_dir / file
        if not file_path.exists():
            raise FileNotFoundError(f"Required file {file} not found in {data_dir}")

        print(f"Loading {file}...")
        dataset[file.split(".")[0]] = pd.read_csv(file_path)

    # Load summary
    summary_path = data_dir / "dataset_summary.json"
    if summary_path.exists():
        with open(summary_path, "r") as f:
            dataset["summary"] = json.load(f)

    return dataset


def format_data_for_llm(
    dataset: Dict[str, pd.DataFrame], max_patients: int = 20, max_observations: int = 5
) -> str:
    """Format the processed data for LLM input.

    Args:
        dataset: Dictionary of processed dataframes
        max_patients: Maximum number of patients to include
        max_observations: Maximum number of observations per patient to include

    Returns:
        Formatted data as a string
    """
    # Start with dataset summary
    if "summary" in dataset:
        formatted_data = "# Dataset Summary\n\n"
        formatted_data += json.dumps(dataset["summary"], indent=2) + "\n\n"
    else:
        formatted_data = ""

    # Add medication effectiveness summary
    formatted_data += "# Medication Effectiveness Summary\n\n"

    outcomes_df = dataset["medication_outcomes"]

    # Focus on HbA1c outcomes
    hba1c_outcomes = outcomes_df[outcomes_df["obs_code"] == "4548-4"]
    if not hba1c_outcomes.empty:
        med_summary = (
            hba1c_outcomes.groupby("med_description")
            .agg({"change": ["mean", "count"], "percent_change": "mean"})
            .reset_index()
        )

        formatted_data += "## HbA1c Outcomes by Medication\n\n"
        formatted_data += "| Medication | Count | Mean Change | Mean % Change |\n"
        formatted_data += "|------------|-------|-------------|---------------|\n"

        for _, row in med_summary.iterrows():
            med_name = row["med_description"]
            count = row[("change", "count")]
            mean_change = row[("change", "mean")]
            mean_pct_change = row[("percent_change", "mean")]

            formatted_data += f"| {med_name} | {count} | {mean_change:.2f} | {mean_pct_change:.2f}% |\n"

        formatted_data += "\n"

    # Add blood glucose outcomes
    glucose_outcomes = outcomes_df[outcomes_df["obs_code"].isin(["2339-0", "2345-7"])]
    if not glucose_outcomes.empty:
        med_summary = (
            glucose_outcomes.groupby("med_description")
            .agg({"change": ["mean", "count"], "percent_change": "mean"})
            .reset_index()
        )

        formatted_data += "## Blood Glucose Outcomes by Medication\n\n"
        formatted_data += "| Medication | Count | Mean Change | Mean % Change |\n"
        formatted_data += "|------------|-------|-------------|---------------|\n"

        for _, row in med_summary.iterrows():
            med_name = row["med_description"]
            count = row[("change", "count")]
            mean_change = row[("change", "mean")]
            mean_pct_change = row[("percent_change", "mean")]

            formatted_data += f"| {med_name} | {count} | {mean_change:.2f} | {mean_pct_change:.2f}% |\n"

        formatted_data += "\n"

    # Select a subset of patients for detailed examples
    patient_outcomes = outcomes_df.groupby("patient").size().reset_index(name="count")
    patient_outcomes = patient_outcomes.sort_values("count", ascending=False)
    selected_patients = patient_outcomes.head(max_patients)["patient"].tolist()

    # Add patient examples
    formatted_data += "# Patient Examples\n\n"

    for patient_id in selected_patients:
        patient_info = dataset["patients_diabetic"][
            dataset["patients_diabetic"]["patient"] == patient_id
        ].iloc[0]

        # Basic patient info
        formatted_data += f"## Patient: {patient_id[:8]}... (anonymized)\n\n"
        formatted_data += f"- Gender: {patient_info['gender']}\n"
        formatted_data += f"- Race: {patient_info['race']}\n"
        formatted_data += f"- Ethnicity: {patient_info['ethnicity']}\n"

        # Get diabetes condition
        diabetes_conditions = dataset["conditions_diabetic"][
            (dataset["conditions_diabetic"]["patient"] == patient_id)
            & (dataset["conditions_diabetic"]["code"].isin(["44054006", "46635009"]))
        ]

        if not diabetes_conditions.empty:
            condition = diabetes_conditions.iloc[0]
            formatted_data += f"- Diabetes Type: {condition['description']}\n"
            formatted_data += f"- Diagnosis Date: {condition['start']}\n\n"

        # Get medications
        patient_meds = dataset["medications_diabetic"][
            dataset["medications_diabetic"]["patient"] == patient_id
        ]

        if not patient_meds.empty:
            formatted_data += "### Medications\n\n"
            formatted_data += "| Start Date | Medication | Reason |\n"
            formatted_data += "|------------|------------|--------|\n"

            for _, med in patient_meds.iterrows():
                formatted_data += f"| {med['start']} | {med['description']} | {med.get('reasondescription', 'N/A')} |\n"

            formatted_data += "\n"

        # Get outcomes
        patient_outcomes = dataset["medication_outcomes"][
            dataset["medication_outcomes"]["patient"] == patient_id
        ]

        if not patient_outcomes.empty:
            formatted_data += "### Health Outcomes\n\n"
            formatted_data += "| Medication | Metric | Before | After | Change | % Change | Days Between |\n"
            formatted_data += "|------------|--------|--------|-------|--------|----------|-------------|\n"

            for _, outcome in patient_outcomes.iterrows():
                med_desc = outcome["med_description"]
                obs_desc = outcome["obs_description"]
                pre_value = outcome["pre_value"]
                post_value = outcome["post_value"]
                change = outcome["change"]
                pct_change = outcome["percent_change"]
                days = outcome["days_between"]

                formatted_data += f"| {med_desc} | {obs_desc} | {pre_value:.2f} | {post_value:.2f} | {change:.2f} | {pct_change:.2f}% | {days} |\n"

            formatted_data += "\n"

        # Get observation timeline (limited to max_observations)
        patient_timeline = dataset["observation_timeline"][
            dataset["observation_timeline"]["patient"] == patient_id
        ]

        if not patient_timeline.empty:
            # Group by medication and observation type
            for (med_code, obs_code), group in patient_timeline.groupby(
                ["med_code", "obs_code"]
            ):
                # Get medication and observation descriptions
                med_desc = group["med_description"].iloc[0]
                obs_desc = group["obs_description"].iloc[0]

                # Sort by days_relative
                group = group.sort_values("days_relative")

                # Select a subset of observations
                if len(group) > max_observations:
                    # Take first, last, and evenly spaced middle observations
                    indices = np.linspace(
                        0, len(group) - 1, max_observations, dtype=int
                    )
                    group = group.iloc[indices]

                formatted_data += f"### Timeline: {med_desc} - {obs_desc}\n\n"
                formatted_data += "| Days from Start | Value | Date |\n"
                formatted_data += "|----------------|-------|------|\n"

                for _, row in group.iterrows():
                    days = row["days_relative"]
                    value = row["value"]
                    date = row["obs_date"]

                    formatted_data += f"| {days} | {value:.2f} | {date} |\n"

                formatted_data += "\n"

        formatted_data += "---\n\n"

    return formatted_data


def save_formatted_data(formatted_data: str, output_file: Union[str, Path]) -> None:
    """Save formatted data to a file.

    Args:
        formatted_data: Formatted data as a string
        output_file: File to save formatted data
    """
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        f.write(formatted_data)

    print(f"Formatted data saved to {output_file}")
    print(f"Approximate token count: {len(formatted_data.split())}")


def main(args: argparse.Namespace) -> None:
    """Main function to load and format data for LLM analysis.

    Args:
        args: Command line arguments
    """
    # Load processed data
    dataset = load_processed_data(args.data_dir)

    # Format data for LLM
    formatted_data = format_data_for_llm(
        dataset, max_patients=args.max_patients, max_observations=args.max_observations
    )

    # Save formatted data
    save_formatted_data(formatted_data, args.output_file)


if __name__ == "__main__":
    args = parse_all_args()
    main(args)
