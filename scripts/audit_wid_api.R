#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(wid))

indicators <- c("sptinc", "shweal")
percentiles <- c("p0p50", "p50p90", "p90p100", "p99p100")

cat("===== WID targeted API audit =====\n")
cat("indicators=", paste(indicators, collapse=","), "\n", sep="")
cat("percentiles=", paste(percentiles, collapse=","), "\n", sep="")

fetch <- function(include_extrapolations) {
	download_wid(
		indicators=indicators,
		areas="all",
		perc=percentiles,
		years="all",
		ages=992,
		pop="j",
		metadata=FALSE,
		include_extrapolations=include_extrapolations,
		verbose=TRUE
	)
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
	country_rows <- data[grepl("^[A-Z]{2}$", data$country), , drop=FALSE]
	cat("twoLetterAreas=", length(unique(country_rows$country)), "\n", sep="")
	cat("twoLetterAreaCodes=", paste(sort(unique(country_rows$country)), collapse=","), "\n", sep="")

	for (variable in sort(unique(country_rows$variable))) {
		for (percentile in percentiles) {
			subset <- country_rows[country_rows$variable == variable & country_rows$percentile == percentile, , drop=FALSE]
			if (nrow(subset) == 0) {
				cat(variable, " ", percentile, ": MISSING\n", sep="")
				next
			}
			latest_by_country <- aggregate(year ~ country, data=subset, FUN=max)
			latest_counts <- sort(table(latest_by_country$year), decreasing=TRUE)
			cat(
				variable, " ", percentile,
				": observations=", nrow(subset),
				" countries=", length(unique(subset$country)),
				" years=", min(subset$year), "..", max(subset$year),
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
		with <- with_extrapolations[
			with_extrapolations$variable == variable &
			with_extrapolations$percentile == percentile &
			grepl("^[A-Z]{2}$", with_extrapolations$country),
			, drop=FALSE
		]
		without <- without_extrapolations[
			without_extrapolations$variable == variable &
			without_extrapolations$percentile == percentile &
			grepl("^[A-Z]{2}$", without_extrapolations$country),
			, drop=FALSE
		]
		with_keys <- paste(with$country, with$year, sep=":")
		without_keys <- paste(without$country, without$year, sep=":")
		removed <- setdiff(with_keys, without_keys)
		cat(variable, " ", percentile, ": removed=", length(removed), " retained=", length(without_keys), "\n", sep="")
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
