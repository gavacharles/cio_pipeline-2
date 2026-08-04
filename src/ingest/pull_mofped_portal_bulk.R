#!/usr/bin/env Rscript

# MOFPED Macro Data Portal bulk download via official API package: ugatsdb
# Adapted from: https://github.com/gavacharles/mofped-macrodata-api-downloader
#
# Usage:
#   Rscript src/ingest/pull_mofped_portal_bulk.R [out_dir] [max_datasets]
# Example:
#   Rscript src/ingest/pull_mofped_portal_bulk.R data/raw/mofped_bulk 5

ensure_pkg <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    install.packages(pkg, repos = "https://cloud.r-project.org")
  }
}

ensure_pkg("ugatsdb")
library(ugatsdb)

if (!nzchar(Sys.getenv("MARIADB_TLS_DISABLE_PEER_VERIFICATION"))) {
  Sys.setenv(MARIADB_TLS_DISABLE_PEER_VERIFICATION = "1")
  message("Set MARIADB_TLS_DISABLE_PEER_VERIFICATION=1 for ugatsdb DB connection.")
}

reconnect_ok <- function(max_tries = 3L, wait_sec = 2L) {
  for (i in seq_len(max_tries)) {
    ok <- tryCatch({
      ugatsdb_reconnect()
      TRUE
    }, error = function(e) FALSE)
    if (ok) return(TRUE)
    Sys.sleep(wait_sec)
  }
  FALSE
}

args <- commandArgs(trailingOnly = TRUE)
out_dir <- if (length(args) >= 1 && nzchar(args[[1]])) args[[1]] else "data/raw/mofped_bulk"
max_n <- if (length(args) >= 2 && nzchar(args[[2]])) as.integer(args[[2]]) else NA_integer_

catalog_dir <- file.path(out_dir, "catalog")
data_dir <- file.path(out_dir, "datasets")
dir.create(catalog_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(data_dir, recursive = TRUE, showWarnings = FALSE)

safe_call <- function(expr) {
  tryCatch(expr, error = function(e) {
    message("ERROR: ", conditionMessage(e))
    NULL
  })
}

if (!reconnect_ok()) {
  message("Warning: ugatsdb_reconnect() failed; proceeding anyway.")
}

message("Fetching catalog tables...")
ds_sources <- safe_call(datasources())
ds_datasets <- safe_call(datasets())
ds_series <- safe_call(series(dataset.info = TRUE))

if (!is.null(ds_sources) && is.data.frame(ds_sources)) {
  write.csv(ds_sources, file.path(catalog_dir, "datasources.csv"), row.names = FALSE, na = "")
}
if (!is.null(ds_datasets) && is.data.frame(ds_datasets)) {
  write.csv(ds_datasets, file.path(catalog_dir, "datasets.csv"), row.names = FALSE, na = "")
}
if (!is.null(ds_series) && is.data.frame(ds_series)) {
  write.csv(ds_series, file.path(catalog_dir, "series.csv"), row.names = FALSE, na = "")
}

if (is.null(ds_datasets) || !is.data.frame(ds_datasets) || nrow(ds_datasets) == 0) {
  message("\nCould not query the API catalog.")
  message("This usually means your network/firewall blocks remote DB access used by ugatsdb.")
  message("Try a different network (e.g., hotspot) or ask IT to allow outbound DB connections.")
  quit(status = 1)
}

find_dsid_col <- function(df) {
  nms <- names(df)
  lower <- tolower(nms)

  direct <- which(lower %in% c("dsid", "dataset", "dataset_id", "datasetid", "id", "code"))
  if (length(direct) > 0) return(nms[direct[1]])

  fuzzy <- grep("dsid|dataset|code|id", lower)
  if (length(fuzzy) > 0) return(nms[fuzzy[1]])

  char_cols <- which(vapply(df, is.character, logical(1)))
  if (length(char_cols) > 0) return(nms[char_cols[1]])

  stop("Could not infer dataset ID column from datasets() table.")
}

dsid_col <- find_dsid_col(ds_datasets)
all_dsids <- unique(na.omit(as.character(ds_datasets[[dsid_col]])))

if (!is.na(max_n)) {
  all_dsids <- utils::head(all_dsids, max_n)
}

message("Found ", length(all_dsids), " datasets to download.")

log_tbl <- data.frame(
  dsid = character(0),
  ok = logical(0),
  rows = integer(0),
  cols = integer(0),
  file = character(0),
  error = character(0),
  stringsAsFactors = FALSE
)

for (i in seq_along(all_dsids)) {
  dsid <- all_dsids[[i]]
  message(sprintf("[%d/%d] %s", i, length(all_dsids), dsid))

  res <- tryCatch({
    dat <- get_data(dsid = dsid, labels = TRUE, wide = TRUE, expand.date = TRUE)

    if (is.null(dat) || !is.data.frame(dat) || nrow(dat) == 0) {
      list(ok = FALSE, rows = 0L, cols = 0L, file = "", error = "Empty dataset")
    } else {
      out_file <- file.path(data_dir, paste0(dsid, ".csv"))
      write.csv(dat, out_file, row.names = FALSE, na = "")
      list(ok = TRUE, rows = nrow(dat), cols = ncol(dat), file = out_file, error = "")
    }
  }, error = function(e) {
    list(ok = FALSE, rows = 0L, cols = 0L, file = "", error = conditionMessage(e))
  })

  log_tbl <- rbind(log_tbl, data.frame(
    dsid = dsid,
    ok = isTRUE(res$ok),
    rows = as.integer(res$rows),
    cols = as.integer(res$cols),
    file = as.character(res$file),
    error = as.character(res$error),
    stringsAsFactors = FALSE
  ))
}

write.csv(log_tbl, file.path(out_dir, "download_log.csv"), row.names = FALSE, na = "")

message("\nDone.")
message("Catalog files: ", normalizePath(catalog_dir, winslash = "/", mustWork = FALSE))
message("Dataset CSVs: ", normalizePath(data_dir, winslash = "/", mustWork = FALSE))
message("Log: ", normalizePath(file.path(out_dir, "download_log.csv"), winslash = "/", mustWork = FALSE))
