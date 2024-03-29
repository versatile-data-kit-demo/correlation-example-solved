# Copyright 2021 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
import pandas as pd
import logging
import os
import pathlib
import time
from vdk.api.job_input import IJobInput

log = logging.getLogger(__name__)
# Make the current directory the same as the job directory
os.chdir(pathlib.Path(__file__).parent.absolute())


def run(job_input: IJobInput):
    """
    Read the ingested yankee candle reviews and do text processing - flag the "no scent" complaints.
    Count the number of "no scent" reviews per day.
    """

    log.info(f"Starting job step {__name__}")

    # Create/retrieve the data job property storing latest ingested date for yankee_candle_reviews_transformed table.
    # If the property does not exist, set it to "2020-01-01" (first ingested date).
    props = job_input.get_all_properties()
    if "last_date_amazon_transformed" in props:
        pass
    else:
        props["last_date_amazon_transformed"] = '2020-01-01'

    # Read the candle review data from the cloud Trino DB and transform it into a df
    reviews_raw = job_input.execute_query(
        f"""
        SELECT *
        FROM {props['prefix']}_yankee_candle_reviews
        WHERE Date > '{props["last_date_amazon_transformed"]}'
        ORDER BY Date
        """
    )
    df = pd.DataFrame(reviews_raw, columns=['date', 'review'])

    # If any data is returned, transform
    if len(df) > 0:
        # Flag the reviews containing scent, smell or fragrance words
        scent_phrases = "scent|smell|fragrance"
        df['flag_no_scent'] = df['review'].str.contains(scent_phrases, case=False, regex=True)

        # Calculate total number of (negative) reviews per day
        df_group = df.groupby('date').count().reset_index()
        df_group = df_group.drop(columns=['flag_no_scent']).rename(columns={'review': 'num_negative_reviews'})

        # Calculate number of "no scent" reviews per day
        df_group2 = df[df['flag_no_scent']==True].groupby('date').count().reset_index()
        df_group2 = df_group2.drop(columns=['review']).rename(columns={'flag_no_scent': 'num_no_scent_reviews'})

        # Combine the columns in one df. Use "left" join to keep the dates with negative reviews
        # but no "no scent" reviews. Fill missing values with 0.
        df_group = df_group.merge(df_group2, on=['date'], how='left').fillna(0)

        # Ingest the transformed df into a new table using VDK's job_input method
        job_input.send_tabular_data_for_ingestion(
            rows=df_group.values,
            column_names=df_group.columns.to_list(),
            destination_table=f"{props['prefix']}_yankee_candle_reviews_transformed"
        )
        # Reset the last_date property value to the latest date in the transformed db table
        props["last_date_amazon_transformed"] = max(df_group['date'])
        job_input.set_all_properties(props)
        log.info(f"Success! {len(df_group)} rows were inserted in yankee_candle_reviews_transformed table.")
        # Delay execution for 10 seconds so that records are ingested into the DB before going to the next script
        time.sleep(10)
    else:
        log.info("No new records to ingest.")
