# Copyright (c) 2024, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import logging
import os
import time

from nemo_curator.datasets import DocumentDataset
from nemo_curator.log import create_logger
from nemo_curator.modules.config import SemDedupConfig
from nemo_curator.modules.semantic_dedup import SemDedup
from nemo_curator.utils.distributed_utils import get_client, read_data
from nemo_curator.utils.file_utils import (
    expand_outdir_and_mkdir,
    get_all_files_paths_under,
)
from nemo_curator.utils.script_utils import ArgumentHelper


def silence_hf_warnings() -> None:
    from transformers.utils import logging

    logging.set_verbosity_error()


def main(args: argparse.Namespace) -> None:
    semdedup_config = SemDedupConfig.from_yaml(args.config_file)
    client = get_client(**ArgumentHelper.parse_client_args(args))

    silence_hf_warnings()
    client.run(silence_hf_warnings)

    expand_outdir_and_mkdir(semdedup_config.cache_dir)
    logger = create_logger(
        rank=0,
        name="logger-end-to_end-semdup",
        log_file=os.path.join(semdedup_config.cache_dir, "compute_embeddings.log"),
        log_level=logging.INFO,
        stdout=True,
    )
    st = time.time()
    input_files = get_all_files_paths_under(
        root=args.input_data_dir,
    )
    if semdedup_config.num_files > 0:
        input_files = input_files[: semdedup_config.num_files]
    logger.info(f"Processing {len(input_files)} files")

    ddf = read_data(
        input_files=input_files,
        file_type=args.input_file_type,
        add_filename=False,
        backend="cudf",
    )
    dataset = DocumentDataset(ddf)
    semdup = SemDedup(
        semdedup_config,
        # Decides whether output of the module is a deduplicated dataset or the IDs of the duplicates
        perform_removal=False,
        logger=logger,
    )
    # When perform_removal=False, it will only call .identify_duplicates() and return the list of duplicate IDs.
    # When perform_removal=True, then exact_dup outputs the dataset with the duplicates removed.
    # It will behave by calling .identify_duplicates() and .remove() in sequence.
    duplicates = semdup(dataset)
    print(duplicates.df.head())
    logger.info(f"Time taken to identify duplicates: {time.time() - st}")

    result = semdup.remove(dataset, duplicates)
    print(result.df.head())
    logger.info(f"Time taken to remove duplicates: {time.time() - st}")

    client.cancel(client.futures, force=True)
    client.close()


def attach_args() -> argparse.ArgumentParser:
    return ArgumentHelper.parse_semdedup_args()


def console_script() -> None:
    main(attach_args().parse_args())


if __name__ == "__main__":
    main(attach_args().parse_args())
