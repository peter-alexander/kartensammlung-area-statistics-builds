#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 5) {
	stop("Usage: download_wid_inequality.R OUTPUT_CSV OUTPUT_METADATA START_YEAR END_YEAR EXPECTED_WID_VERSION")
}

output_csv <- args[[1]]
output_metadata <- args[[2]]
start_year <- as.integer(args[[3]])
end_year <- as.integer(args[[4]])
expected_version <- args[[5]]

if (is.na(start_year) || is.na(end_year) || start_year < 1900 || end_year < start_year) {
	stop("Invalid WID year range")
}

suppressPackageStartupMessages(library(wid))
suppressPackageStartupMessages(library(jsonlite))

actual_version <- as.character(packageVersion("wid"))
if (actual_version != expected_version) {
	stop(sprintf("Unexpected wid package version: %s != %s", actual_version, expected_version))
}

arguments <- names(formals(download_wid))
required_arguments <- c("indicators", "areas", "years", "perc", "ages", "pop", "metadata", "quality_filter", "verbose")
missing_arguments <- setdiff(required_arguments, arguments)
if (length(missing_arguments) > 0) {
	stop(sprintf("wid download_wid API changed; missing arguments: %s", paste(missing_arguments, collapse = ",")))
}
if ("include_extrapolations" %in% arguments) {
	stop("Unexpected legacy wid download_wid API detected")
}

years <- start_year:end_year

shares <- download_wid(
	indicators = "sptinc",
	areas = "all",
	years = years,
	perc = c("p0p50", "p90p100", "p99p100"),
	ages = "992",
	pop = "j",
	metadata = FALSE,
	quality_filter = NULL,
	verbose = TRUE
)

gini <- download_wid(
	indicators = "gptinc",
	areas = "all",
	years = years,
	perc = "p0p100",
	ages = "992",
	pop = "j",
	metadata = FALSE,
	quality_filter = NULL,
	verbose = TRUE
)

if (is.null(shares) || nrow(shares) == 0) {
	stop("WID returned no pre-tax income share data")
}
if (is.null(gini) || nrow(gini) == 0) {
	stop("WID returned no pre-tax income Gini data")
}

data <- rbind(shares, gini)
required_columns <- c("country", "variable", "percentile", "year", "value", "data_quality")
missing_columns <- setdiff(required_columns, names(data))
if (length(missing_columns) > 0) {
	stop(sprintf("WID response missing columns: %s", paste(missing_columns, collapse = ",")))
}

expected_variables <- c("gptinc992j", "sptinc992j")
actual_variables <- sort(unique(as.character(data$variable)))
if (!identical(actual_variables, expected_variables)) {
	stop(sprintf("Unexpected WID variables: %s", paste(actual_variables, collapse = ",")))
}

expected_percentiles <- c("p0p100", "p0p50", "p90p100", "p99p100")
actual_percentiles <- sort(unique(as.character(data$percentile)))
if (!identical(actual_percentiles, sort(expected_percentiles))) {
	stop(sprintf("Unexpected WID percentiles: %s", paste(actual_percentiles, collapse = ",")))
}

data <- data[order(data$country, data$variable, data$percentile, data$year), ]
dir.create(dirname(output_csv), recursive = TRUE, showWarnings = FALSE)
dir.create(dirname(output_metadata), recursive = TRUE, showWarnings = FALSE)
write.csv(data, output_csv, row.names = FALSE, na = "")

quality_table <- table(data$data_quality, useNA = "ifany")
metadata <- list(
	retrievedAt = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
	package = list(
		name = "wid",
		version = actual_version,
		url = "https://CRAN.R-project.org/package=wid"
	),
	query = list(
		startYear = start_year,
		endYear = end_year,
		areas = "all",
		age = "992",
		population = "j",
		metadata = FALSE,
		qualityFilter = NULL,
		series = list(
			list(indicator = "sptinc", percentiles = c("p0p50", "p90p100", "p99p100")),
			list(indicator = "gptinc", percentiles = c("p0p100"))
		)
	),
	rows = nrow(data),
	variables = actual_variables,
	percentiles = actual_percentiles,
	dataQualityCounts = as.list(quality_table)
)
write_json(metadata, output_metadata, pretty = TRUE, auto_unbox = TRUE, null = "null")
cat(sprintf("WID rows=%d variables=%s quality=%s\n", nrow(data), paste(actual_variables, collapse = ","), paste(names(quality_table), quality_table, sep = ":", collapse = ",")))
