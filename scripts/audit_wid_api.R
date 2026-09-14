#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(wid))
suppressPackageStartupMessages(library(jsonlite))

indicators <- c("sptinc", "shweal")
percentiles <- c("p0p50", "p50p90", "p90p100", "p99p100")
registry_url <- "https://tiles.radlobby.at/AreaStatistics/area-registry-countries.json"
wid_countries_url <- "https://wid.world/bulk_download/WID_countries.csv"

registry <- fromJSON(registry_url, simplifyVector=FALSE)
registry_codes <- sort(unique(vapply(
	registry$areas,
	function(area) {
		if (!identical(area$level, "country")) return(NA_character_)
		code <- area$codes$iso2
		if (is.null(code)) return(NA_character_)
		as.character(code)
	},
	character(1)
)))
registry_codes <- registry_codes[!is.na(registry_codes) & grepl("^[A-Z]{2}$", registry_codes)]
if (length(registry_codes) != 250) {
	stop(paste("Expected 250 two-letter registry country codes, got", length(registry_codes)))
}

wid_countries <- read.csv(wid_countries_url, sep=";", stringsAsFactors=FALSE, check.names=FALSE)
if (!("alpha2" %in% names(wid_countries))) {
	stop("WID_countries.csv has no alpha2 column")
}
wid_codes <- sort(unique(toupper(trimws(wid_countries$alpha2))))
wid_codes <- wid_codes[grepl("^[A-Z]{2}$", wid_codes)]
query_codes <- intersect(registry_codes, wid_codes)
if (length(query_codes) != 232) {
	stop(paste("Expected 232 WID/registry ISO2 overlaps, got", length(query_codes)))
}

cat("===== WID targeted API audit =====\n")
cat("indicators=", paste(indicators, collapse=","), "\n", sep="")
cat("percentiles=", paste(percentiles, collapse=","), "\n", sep="")
cat("registryCountries=", length(registry_codes), "\n", sep="")
cat("widTwoLetterCodes=", length(wid_codes), "\n", sep="")
cat("queryCountries=", length(query_codes), "\n", sep="")
cat("registryWithoutWIDCode=", paste(setdiff(registry_codes, wid_codes), collapse=","), "\n", sep="")

fetch <- function(include_extrapolations) {
	download_wid(
		indicators=indicators,
		areas=query_codes,
		perc=percentiles,
		years="all",
		ages=992,
		pop="j",
		metadata=FALSE,
		include_extrapolations=include_extrapolations,
		verbose=TRUE
	)
}

registry_rows <- function(data) {
	data[data$country %in% query_codes, , drop=FALSE]
}

summarize_data <- function(data, label) {
	cat("\n===== ", label, " =====\n", sep="")
	if (is.null(data) || nrow(data) == 0) {
		stop(paste("No WID data returned for", label))
	}
	cat("columns=", paste(names(data), collapse=","), "\n", sep="")
	cat("rows=", nrow(data), "\n", sep="")
	cat("variables=", paste(sort(unique(data$variable)), collapse=","), "\n", sep="")
	cat("percentiles=", paste(sort(unique(data$percentile)), collapse=","), "\n", sep="")
	country_rows <- registry_rows(data)
	returned_codes <- sort(unique(country_rows$country))
	cat("mappedRegistryCountries=", length(returned_codes), "\n", sep="")
	cat("queriedButNoTargetData=", paste(setdiff(query_codes, returned_codes), collapse=","), "\n", sep="")

	for (variable in sort(unique(country_rows$variable))) {
		for (percentile in percentiles) {
			subset <- country_rows[country_rows$variable == variable & country_rows$percentile == percentile, , drop=FALSE]
			if (nrow(subset) == 0) {
				cat(variable, " ", percentile, ": MISSING\n", sep="")
				next
			}
			latest_by_country <- aggregate(year ~ country, data=subset, FUN=max)
			latest_counts <- sort(table(latest_by_country$year), decreasing=TRUE)
			coverage_2024 <- length(unique(subset$country[subset$year == 2024]))
			coverage_2023 <- length(unique(subset$country[subset$year == 2023]))
			cat(
				variable, " ", percentile,
				": observations=", nrow(subset),
				" countries=", length(unique(subset$country)),
				" years=", min(subset$year), "..", max(subset$year),
				" coverage2024=", coverage_2024,
				" coverage2023=", coverage_2023,
				" latestYearDistribution=",
				paste(names(latest_counts), as.integer(latest_counts), sep=":", collapse=","),
				"\n", sep=""
			)
		}
	}
}

with_extrapolations <- fetch(TRUE)
without_extrapolations <- fetch(FALSE)

summarize_data(with_extrapolations, "including interpolations/extrapolations")
summarize_data(without_extrapolations, "excluding interpolations/extrapolations")

cat("\n===== extrapolation effect by variable/percentile =====\n")
for (variable in sort(unique(with_extrapolations$variable))) {
	for (percentile in percentiles) {
		with <- registry_rows(with_extrapolations[
			with_extrapolations$variable == variable &
			with_extrapolations$percentile == percentile,
			, drop=FALSE
		])
		without <- registry_rows(without_extrapolations[
			without_extrapolations$variable == variable &
			without_extrapolations$percentile == percentile,
			, drop=FALSE
		])
		with_keys <- paste(with$country, with$year, sep=":")
		without_keys <- paste(without$country, without$year, sep=":")
		removed <- setdiff(with_keys, without_keys)
		cat(
			variable, " ", percentile,
			": removed=", length(removed),
			" retained=", length(without_keys),
			" removalPct=", round(100 * length(removed) / max(1, length(with_keys)), 2),
			"\n", sep=""
		)
	}
}

cat("\n===== sample metadata =====\n")
metadata_sample <- download_wid(
	indicators=indicators,
	areas=c("AT", "US", "FR"),
	perc=c("p0p50", "p90p100", "p99p100"),
	years="all",
	ages=992,
	pop="j",
	metadata=TRUE,
	include_extrapolations=TRUE,
	verbose=TRUE
)
cat("metadataColumns=", paste(names(metadata_sample), collapse=","), "\n", sep="")
meta_cols <- intersect(c("country", "variable", "percentile", "countryname", "shortname", "shortdes", "pop", "age", "source", "method", "imputation", "quality"), names(metadata_sample))
metadata_unique <- unique(metadata_sample[, meta_cols, drop=FALSE])
print(metadata_unique, row.names=FALSE)
