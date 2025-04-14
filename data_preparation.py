#!/usr/bin/env python3

import pandas as pd
import numpy as np
from pathlib import Path
import argparse
from typing import Dict, List, Optional, Set, Union
import json

def parse_all_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for data preparation.
    
    Args:
        args: Command line arguments. If None, sys.argv[1:] is used.
        
    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(description="Prepare Siyeh synthetic medical data for LLM analysis")
    parser.add_argument(
        "--data_dir", 
        type=str, 
        default="data/siyeh-synthetic-medical-data/data",
        help="Directory containing the Siyeh dataset CSV files"
    )
    parser.add_argument(
        "--output_dir", 
        type=str, 
        default="data/processed",
        help="Directory to save processed data files"
    )
    parser.add_argument(
        "--diabetes_codes", 
        type=str, 
        nargs="+", 
        default=["44054006", "15777000", "422034002", "1551000119108", "97331000119101", "368581000119106"],
        help="SNOMED CT codes for diabetes and related conditions"
    )
    parser.add_argument(
        "--glucose_codes", 
        type=str, 
        nargs="+", 
        default=["2339-0", "2345-7", "4548-4"],
        help="LOINC codes for glucose measurements (2339-0: glucose, 2345-7: glucose [mass/volume], 4548-4: HbA1c)"
    )
    parser.add_argument(
        "--include_comorbidities", 
        action="store_true",
        help="Include comorbidity conditions for diabetic patients"
    )
    parser.add_argument(
        "--include_vitals", 
        action="store_true",
        help="Include vital signs like BMI and blood pressure for diabetic patients"
    )
    
    return parser.parse_args(args)

def load_dataset(data_dir: Union[str, Path]) -> Dict[str, pd.DataFrame]:
    """Load the Siyeh dataset CSV files.
    
    Args:
        data_dir: Directory containing the dataset CSV files
        
    Returns:
        Dictionary of dataframes for each CSV file
    """
    data_dir = Path(data_dir)
    required_files = ["patients.csv", "conditions.csv", "medications.csv", "observations.csv"]
    
    dataset = {}
    for file in required_files:
        file_path = data_dir / file
        if not file_path.exists():
            raise FileNotFoundError(f"Required file {file} not found in {data_dir}")
        
        print(f"Loading {file}...")
        dataset[file.split('.')[0]] = pd.read_csv(file_path)
        
    return dataset

def identify_diabetic_patients(conditions_df: pd.DataFrame, diabetes_codes: List[str]) -> Set[str]:
    """Identify patients with diabetes based on condition codes.
    
    Args:
        conditions_df: DataFrame containing condition records
        diabetes_codes: List of SNOMED CT codes for diabetes
        
    Returns:
        Set of patient IDs with diabetes
    """
    # First approach: Use the provided diabetes codes
    diabetes_conditions = conditions_df[conditions_df["code"].isin(diabetes_codes)]
    diabetic_patients = set(diabetes_conditions["patient"].unique())
    
    # Second approach: Use text matching for additional cases
    diabetes_desc_conditions = conditions_df[conditions_df["description"].str.contains("diabetes|diabetic", case=False, na=False)]
    diabetic_patients_desc = set(diabetes_desc_conditions["patient"].unique())
    
    # Combine both approaches
    all_diabetic_patients = diabetic_patients.union(diabetic_patients_desc)
    
    print(f"Identified {len(all_diabetic_patients)} patients with diabetes")
    print(f"  - {len(diabetic_patients)} patients identified by code")
    print(f"  - {len(diabetic_patients_desc)} patients identified by description")
    
    return all_diabetic_patients

def filter_dataset_for_diabetic_patients(
    dataset: Dict[str, pd.DataFrame], 
    diabetic_patients: Set[str],
    include_comorbidities: bool = False
) -> Dict[str, pd.DataFrame]:
    """Filter the dataset to include only diabetic patients.
    
    Args:
        dataset: Dictionary of dataframes
        diabetic_patients: Set of patient IDs with diabetes
        include_comorbidities: Whether to include all conditions or just diabetes
        
    Returns:
        Filtered dataset
    """
    filtered_dataset = {}
    
    # Filter patients
    filtered_dataset["patients"] = dataset["patients"][
        dataset["patients"]["patient"].isin(diabetic_patients)
    ]
    
    # Filter conditions (either all conditions for diabetic patients or just diabetes)
    if include_comorbidities:
        filtered_dataset["conditions"] = dataset["conditions"][
            dataset["conditions"]["patient"].isin(diabetic_patients)
        ]
    else:
        filtered_dataset["conditions"] = dataset["conditions"][
            dataset["conditions"]["patient"].isin(diabetic_patients) & 
            dataset["conditions"]["code"].isin(["44054006", "46635009"])
        ]
    
    # Filter medications
    filtered_dataset["medications"] = dataset["medications"][
        dataset["medications"]["patient"].isin(diabetic_patients)
    ]
    
    # Filter observations
    filtered_dataset["observations"] = dataset["observations"][
        dataset["observations"]["patient"].isin(diabetic_patients)
    ]
    
    return filtered_dataset

def filter_relevant_observations(
    observations_df: pd.DataFrame, 
    glucose_codes: List[str],
    include_vitals: bool = False
) -> pd.DataFrame:
    """Filter observations to include only relevant health metrics.
    
    Args:
        observations_df: DataFrame containing observation records
        glucose_codes: List of LOINC codes for glucose measurements
        include_vitals: Whether to include vital signs
        
    Returns:
        Filtered observations DataFrame
    """
    # Always include glucose measurements
    relevant_obs = observations_df[observations_df["code"].isin(glucose_codes)]
    
    # Optionally include vital signs
    if include_vitals:
        # BMI code: 39156-5, Systolic BP: 8480-6, Diastolic BP: 8462-4
        vital_codes = ["39156-5", "8480-6", "8462-4"]
        vitals_obs = observations_df[observations_df["code"].isin(vital_codes)]
        relevant_obs = pd.concat([relevant_obs, vitals_obs])
    
    return relevant_obs

def create_medication_periods(medications_df: pd.DataFrame) -> pd.DataFrame:
    """Create a DataFrame with medication periods for each patient.
    
    Args:
        medications_df: DataFrame containing medication records
        
    Returns:
        DataFrame with medication periods
    """
    # Convert date columns to datetime
    medications_df["start"] = pd.to_datetime(medications_df["start"])
    medications_df["stop"] = pd.to_datetime(medications_df["stop"])
    
    # Fill missing stop dates with a future date
    medications_df["stop"] = medications_df["stop"].fillna(pd.Timestamp.max)
    
    return medications_df

def create_observation_timeline(
    observations_df: pd.DataFrame, 
    medication_periods_df: pd.DataFrame
) -> pd.DataFrame:
    """Create a timeline of observations relative to medication start dates.
    
    Args:
        observations_df: DataFrame containing observation records
        medication_periods_df: DataFrame with medication periods
        
    Returns:
        DataFrame with observations and relative time to medication
    """
    # If either dataframe is empty, return an empty dataframe
    if observations_df.empty or medication_periods_df.empty:
        print("Warning: Empty observations or medications dataframe")
        return pd.DataFrame()
    
    # Convert date column to datetime
    observations_df["date"] = pd.to_datetime(observations_df["date"])
    
    # Convert value column to numeric
    observations_df["value"] = pd.to_numeric(observations_df["value"], errors="coerce")
    
    # Initialize an empty list to store results
    timeline_records = []
    
    # Process each patient
    for patient in observations_df["patient"].unique():
        patient_obs = observations_df[observations_df["patient"] == patient]
        patient_meds = medication_periods_df[medication_periods_df["patient"] == patient]
        
        # Skip patients with no medications
        if len(patient_meds) == 0:
            continue
        
        # For each medication
        for _, med_row in patient_meds.iterrows():
            med_start = med_row["start"]
            med_code = med_row["code"]
            med_desc = med_row["description"]
            
            # For each observation
            for _, obs_row in patient_obs.iterrows():
                obs_date = obs_row["date"]
                
                # Calculate days relative to medication start
                days_relative = (obs_date - med_start).days
                
                # Create a record
                record = {
                    "patient": patient,
                    "med_code": med_code,
                    "med_description": med_desc,
                    "med_start_date": med_start,
                    "obs_code": obs_row["code"],
                    "obs_description": obs_row["description"],
                    "obs_date": obs_date,
                    "days_relative": days_relative,
                    "value": obs_row["value"],
                    "units": obs_row["units"]
                }
                
                timeline_records.append(record)
    
    # Create DataFrame from records
    timeline_df = pd.DataFrame(timeline_records)
    
    return timeline_df

def create_patient_medication_outcomes(timeline_df: pd.DataFrame) -> pd.DataFrame:
    """Create a summary of medication outcomes for each patient.
    
    Args:
        timeline_df: DataFrame with observation timeline
        
    Returns:
        DataFrame with medication outcomes
    """
    # If timeline is empty, return an empty dataframe
    if timeline_df.empty:
        print("Warning: Empty timeline dataframe")
        return pd.DataFrame()
    
    # Ensure value column is numeric
    timeline_df["value"] = pd.to_numeric(timeline_df["value"], errors="coerce")
    
    # Initialize an empty list to store results
    outcome_records = []
    
    # Group by patient and medication
    for (patient, med_code, med_desc), group in timeline_df.groupby(["patient", "med_code", "med_description"]):
        # Group observations by type
        for obs_code, obs_group in group.groupby("obs_code"):
            # Skip if less than 2 observations
            if len(obs_group) < 2:
                continue
                
            # Get the observation description
            obs_desc = obs_group["obs_description"].iloc[0]
            units = obs_group["units"].iloc[0]
            
            # Sort by days_relative
            obs_group = obs_group.sort_values("days_relative")
            
            # Get pre-medication values (days_relative <= 0)
            pre_med = obs_group[obs_group["days_relative"] <= 0]
            if len(pre_med) > 0:
                pre_value = pre_med.iloc[-1]["value"]  # Most recent pre-medication value
                pre_date = pre_med.iloc[-1]["obs_date"]
            else:
                continue  # Skip if no pre-medication values
            
            # Get post-medication values (days_relative > 0)
            post_med = obs_group[obs_group["days_relative"] > 0]
            if len(post_med) > 0:
                # Find observations around 3-6 months after medication start
                target_days = 180  # ~6 months
                post_med["days_diff"] = abs(post_med["days_relative"] - target_days)
                closest_idx = post_med["days_diff"].idxmin()
                post_value = post_med.loc[closest_idx, "value"]
                post_date = post_med.loc[closest_idx, "obs_date"]
                actual_days = post_med.loc[closest_idx, "days_relative"]
            else:
                continue  # Skip if no post-medication values
            
            # Calculate change
            try:
                change = float(post_value) - float(pre_value)
                percent_change = (change / float(pre_value)) * 100 if float(pre_value) != 0 else np.nan
            except (ValueError, TypeError):
                print(f"Warning: Could not calculate change for values {pre_value} and {post_value}")
                change = np.nan
                percent_change = np.nan
            
            # Create a record
            record = {
                "patient": patient,
                "med_code": med_code,
                "med_description": med_desc,
                "obs_code": obs_code,
                "obs_description": obs_desc,
                "pre_value": pre_value,
                "post_value": post_value,
                "change": change,
                "percent_change": percent_change,
                "pre_date": pre_date,
                "post_date": post_date,
                "days_between": actual_days,
                "units": units
            }
            
            outcome_records.append(record)
    
    # Create DataFrame from records
    outcomes_df = pd.DataFrame(outcome_records)
    
    return outcomes_df

def save_processed_data(
    filtered_dataset: Dict[str, pd.DataFrame],
    timeline_df: pd.DataFrame,
    outcomes_df: pd.DataFrame,
    output_dir: Union[str, Path]
) -> None:
    """Save processed data to CSV files.
    
    Args:
        filtered_dataset: Dictionary of filtered dataframes
        timeline_df: DataFrame with observation timeline
        outcomes_df: DataFrame with medication outcomes
        output_dir: Directory to save processed data files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save filtered datasets
    for name, df in filtered_dataset.items():
        df.to_csv(output_dir / f"{name}_diabetic.csv", index=False)
    
    # Save timeline and outcomes
    timeline_df.to_csv(output_dir / "observation_timeline.csv", index=False)
    outcomes_df.to_csv(output_dir / "medication_outcomes.csv", index=False)
    
    # Create a summary of the dataset
    summary = {
        "num_diabetic_patients": len(filtered_dataset["patients"]),
        "num_diabetes_conditions": len(filtered_dataset["conditions"]),
        "num_medications": len(filtered_dataset["medications"]),
        "num_observations": len(filtered_dataset["observations"]),
        "num_medication_outcomes": len(outcomes_df)
    }
    
    # Add metrics and medications if available
    if not outcomes_df.empty:
        summary["glucose_metrics_tracked"] = outcomes_df["obs_description"].unique().tolist()
        summary["medications_analyzed"] = outcomes_df["med_description"].unique().tolist()
    else:
        summary["glucose_metrics_tracked"] = []
        summary["medications_analyzed"] = []
    
    with open(output_dir / "dataset_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"Processed data saved to {output_dir}")

def main(args: argparse.Namespace) -> None:
    """Main function to prepare data for LLM analysis.
    
    Args:
        args: Command line arguments
    """
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load dataset
    dataset = load_dataset(args.data_dir)
    
    # Identify diabetic patients
    diabetic_patients = identify_diabetic_patients(dataset["conditions"], args.diabetes_codes)
    
    # Filter dataset for diabetic patients
    filtered_dataset = filter_dataset_for_diabetic_patients(
        dataset, 
        diabetic_patients,
        include_comorbidities=args.include_comorbidities
    )
    
    # Filter observations for relevant health metrics
    filtered_dataset["observations"] = filter_relevant_observations(
        filtered_dataset["observations"],
        args.glucose_codes,
        include_vitals=args.include_vitals
    )
    
    # Create medication periods
    medication_periods = create_medication_periods(filtered_dataset["medications"])
    
    # Create observation timeline
    timeline_df = create_observation_timeline(filtered_dataset["observations"], medication_periods)
    
    # Create medication outcomes
    outcomes_df = create_patient_medication_outcomes(timeline_df)
    
    # Save processed data
    save_processed_data(filtered_dataset, timeline_df, outcomes_df, args.output_dir)
    
    # Print some statistics
    print(f"\nProcessed {len(diabetic_patients)} diabetic patients")
    print(f"Created {len(timeline_df)} observation timeline records")
    print(f"Identified {len(outcomes_df)} medication outcome records")
    
    # Print medication effectiveness summary
    if not outcomes_df.empty:
        print("\nMedication Effectiveness Summary (for HbA1c):")
        hba1c_outcomes = outcomes_df[outcomes_df["obs_code"] == "4548-4"]
        if not hba1c_outcomes.empty:
            med_summary = hba1c_outcomes.groupby("med_description").agg({
                "change": ["mean", "count"],
                "percent_change": "mean"
            })
            print(med_summary)
    else:
        print("\nNo medication outcomes found. This could be due to:")
        print("1. No diabetic patients found with the specified codes")
        print("2. No relevant observations for diabetic patients")
        print("3. No medications prescribed to diabetic patients")
        
        # Print some debugging information
        print(f"\nDiabetic patients found: {len(diabetic_patients)}")
        print(f"Filtered conditions: {len(filtered_dataset['conditions'])}")
        print(f"Filtered medications: {len(filtered_dataset['medications'])}")
        print(f"Filtered observations: {len(filtered_dataset['observations'])}")

if __name__ == "__main__":
    args = parse_all_args()
    main(args)
