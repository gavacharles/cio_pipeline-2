#!/usr/bin/env Rscript
# pull_ugatsdb.R
# =============================================================================
# Pull the macroeconomic block for the CiO price-panel from the MoFPED
# Macro Data Portal via the `ugatsdb` API, and export to Parquet/CSV so the
# Python pipeline can consume it.
#
# WHY R HERE: the MoFPED portal ships an official R client (`ugatsdb`, on CRAN)
# that connects directly to the portal's relational database. Using it is more
# robust and more reproducible than scraping the web UI. This thin wrapper is
# the ONLY R in the pipeline; everything downstream is Python.
#
# FIREWALL NOTE: `ugatsdb` opens a direct remote database connection. Some
# institutional networks block all outbound DB connections, in which case this
# script will fail at get_data(). The documented fallback is to export the same
# series manually from the portal's "Download Data" tab as CSV and drop them
# into data/raw/macro_manual/ ; set USE_MANUAL_FALLBACK=TRUE below to use those.
#
# Usage:  Rscript pull_ugatsdb.R  [start_date]  [out_dir]
#         Rscript pull_ugatsdb.R  2016-01-01    ../data/raw
# =============================================================================

suppressWarnings({
  args <- commandArgs(trailingOnly = TRUE)
  start_date <- if (length(args) >= 1) args[[1]] else "2016-01-01"
  out_dir    <- if (length(args) >= 2) args[[2]] else "data/raw"
  dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

  USE_MANUAL_FALLBACK <- tolower(Sys.getenv("USE_MANUAL_FALLBACK", "false")) %in% c("1", "true", "yes")

  # ------------------------------------------------------------------ packages
  need <- c("ugatsdb", "collapse", "arrow")
  for (p in need) {
    if (!requireNamespace(p, quietly = TRUE)) {
      message(sprintf("Installing missing package: %s", p))
      try(install.packages(p, repos = "https://cloud.r-project.org"), silent = TRUE)
    }
  }
  library(ugatsdb)

  # Same connectivity hardening used in
  # https://github.com/gavacharles/mofped-macrodata-api-downloader
  if (!nzchar(Sys.getenv("MARIADB_TLS_DISABLE_PEER_VERIFICATION"))) {
    Sys.setenv(MARIADB_TLS_DISABLE_PEER_VERIFICATION = "1")
    message("Set MARIADB_TLS_DISABLE_PEER_VERIFICATION=1 for ugatsdb DB connection.")
  }

  reconnect_ok <- function(max_tries = 3L, wait_sec = 2L) {
    for (i in seq_len(max_tries)) {
      ok <- tryCatch({
        ugatsdb::ugatsdb_reconnect()
        TRUE
      }, error = function(e) FALSE)
      if (ok) return(TRUE)
      Sys.sleep(wait_sec)
    }
    FALSE
  }

  if (!reconnect_ok()) {
    message("Warning: ugatsdb_reconnect() failed; proceeding anyway.")
  }

  # --------------------------------------------------------------- series map
  # dataset code -> series code(s) we need, with the stable name we assign.
  # These codes come from the portal's Data Catalog / API tab. Adjust if the
  # catalogue is revised; datasets() and series() list the current codes.
  #   BOU_E    : exchange rates (UGX/USD)         -> monthly
  #   BOU_MMI  : money-market indicators (CBR, interbank, T-bill) -> monthly
  #   BOU_I    : commercial bank interest/lending rates -> monthly
  #   UBOS_CPI (via BOU_CPI mirror) : consumer price index -> monthly
  #   BOU_PSC  : private sector credit             -> monthly
  #   UBOS_GDP_CP : nominal GDP (quarterly)        -> quarterly (interp. later)
  wanted <- list(
    exchange_rate     = list(dataset = "BOU_E",   series = "E_PERIOD_AVG_USD"),
    central_bank_rate = list(dataset = "BOU_MMI", series = "CBR"),
    lending_rate      = list(dataset = "BOU_I",   series = "LENDING_RATE"),
    cpi               = list(dataset = "BOU_CPI", series = "CPI_HEADLINE"),
    private_credit    = list(dataset = "BOU_PSC", series = "PSC_TOTAL")
  )

  pull_one <- function(spec) {
    out <- tryCatch(
      ugatsdb::get_data(spec$dataset, from = start_date, wide = FALSE),
      error = function(e) {
        structure(NULL, .err = conditionMessage(e))
      }
    )
    out
  }

  if (USE_MANUAL_FALLBACK) {
    message("USE_MANUAL_FALLBACK=TRUE: reading CSVs from data/raw/macro_manual/")
    files <- list.files(file.path(out_dir, "macro_manual"),
                        pattern = "\\.csv$", full.names = TRUE)
    macro <- do.call(rbind, lapply(files, function(f) {
      d <- utils::read.csv(f); d$source_csv <- basename(f); d
    }))
  } else {
    message("Pulling macro block from MoFPED portal via ugatsdb ...")
    frames <- list(); failures <- list()
    for (nm in names(wanted)) {
      d <- pull_one(wanted[[nm]])
      if (!is.null(d) && nrow(d) > 0) {
        d$var <- nm
        frames[[nm]] <- d
        message(sprintf("  %-18s: %d rows", nm, nrow(d)))
      } else {
        err <- attr(d, ".err")
        if (is.null(err)) err <- "empty result (likely connection blocked or bad series code)"
        failures[[length(failures) + 1]] <- data.frame(
          var = nm,
          dataset = wanted[[nm]]$dataset,
          series = wanted[[nm]]$series,
          error = err,
          stringsAsFactors = FALSE
        )
        message(sprintf("  %-18s: FAILED (%s)", nm, err))
      }
    }
    if (length(failures)) {
      fail_df <- do.call(rbind, failures)
      fail_path <- file.path(out_dir, "ugatsdb_failures.csv")
      utils::write.csv(fail_df, fail_path, row.names = FALSE)
      message("Wrote ", fail_path)
    }
    if (length(frames) == 0)
      stop("No macro series retrieved. If inside an institutional network, ",
           "the portal DB is likely firewalled: export CSVs manually and set ",
           "USE_MANUAL_FALLBACK=TRUE.")
    macro <- do.call(rbind, frames)
  }

  # ------------------------------------------------------------------- export
  csv_path <- file.path(out_dir, "macro_block.csv")
  utils::write.csv(macro, csv_path, row.names = FALSE)
  message("Wrote ", csv_path, " (", nrow(macro), " rows)")

  # Parquet for the Python side (falls back silently if arrow is unavailable).
  if (requireNamespace("arrow", quietly = TRUE)) {
    pq_path <- file.path(out_dir, "macro_block.parquet")
    arrow::write_parquet(macro, pq_path)
    message("Wrote ", pq_path)
  }
  message("Done.")
})
