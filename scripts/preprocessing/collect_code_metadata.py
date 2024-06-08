#!/usr/bin/env python

import json
import random
import time
from datetime import datetime
from pathlib import Path

import hydra
import polars as pl
from loguru import logger
from omegaconf import DictConfig, OmegaConf

from MEDS_polars_functions.code_metadata import mapper_fntr, reducer_fntr
from MEDS_polars_functions.mapper import wrap as rwlock_wrap
from MEDS_polars_functions.utils import hydra_loguru_init, write_lazyframe


@hydra.main(version_base=None, config_path="configs", config_name="preprocess")
def main(cfg: DictConfig):
    """Computes code metadata."""

    hydra_loguru_init()

    logger.info(
        f"Running with config:\n{OmegaConf.to_yaml(cfg)}\n"
        f"Stage: {cfg.stage}\n\n"
        f"Stage config:\n{OmegaConf.to_yaml(cfg.stage_cfg)}"
    )

    input_dir = Path(cfg.stage_cfg.data_input_dir)
    output_dir = Path(cfg.stage_cfg.output_dir)

    logger.info(f"Reading data from input directory {str(input_dir.resolve())}")

    shards = json.loads((Path(cfg.input_dir) / "splits.json").read_text())

    patient_splits = list(shards.keys())
    random.shuffle(patient_splits)

    mapper_fn = mapper_fntr(cfg.stage_cfg, cfg.get("code_modifier_columns", None))

    start = datetime.now()
    logger.info("Starting code metadata mapping computation")

    all_out_fps = []
    for sp in patient_splits:
        in_fp = input_dir / f"{sp}.parquet"
        out_fp = output_dir / f"{sp}.parquet"
        all_out_fps.append(out_fp)

        logger.info(
            f"Computing code metadata for {str(in_fp.resolve())} and storing to {str(out_fp.resolve())}"
        )

        rwlock_wrap(
            in_fp,
            out_fp,
            pl.scan_parquet,
            write_lazyframe,
            mapper_fn,
            do_return=False,
            cache_intermediate=False,
            do_overwrite=cfg.do_overwrite,
        )

    logger.info(f"Finished mapping in {datetime.now() - start}")

    if cfg.worker != 1:
        return

    while not all(fp.is_file() for fp in all_out_fps):
        logger.info("Waiting to begin reduction for all files to be written...")
        time.sleep(cfg.polling_time)

    start = datetime.now()
    logger.info("All map shards complete! Starting code metadata reduction computation.")
    reducer_fn = reducer_fntr(cfg.stage_cfg, cfg.get("code_modifier_columns", None))

    reduced = reducer_fn(pl.scan_parquet(fp, glob=False) for fp in all_out_fps)
    write_lazyframe(reduced, output_dir / "code_metadata.parquet")
    logger.info(f"Finished reduction in {datetime.now() - start}")


if __name__ == "__main__":
    main()
