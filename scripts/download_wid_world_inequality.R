#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 6) {
	stop("Usage: download_wid_world_inequality.R OUTPUT_CSV OUTPUT_METADATA REGISTRY_URL EXPECTED_COMMIT EXPECTED_VERSION WID_COUNTRIES_URL")
}

output_csv <- args[[1]]
output_metadata <- args[[2]]
registry_url <- args[[3]]
expected_commit <- args[[4]]
expected_version <- args[[5]]
wid_countries_url <- args[[6]]

suppressPackageStartupMessages(library(wid))
suppressPackageStartupMessages(library(jsonlite))

actual_version <- as.character(packageVersion("wid"))
if (actual_version != expected_version) {
	stop(sprintf("Unexpected wid package version: %s != %s", actual_version, expected_version))
}

arguments <- names(formals(download_wid))
required_arguments <- c(
	"indicators", "areas", "years", "perc", "ages", "pop",
	"metadata", "include_extrapolations", "verbose"
)
missing_arguments <- setdiff(required_arguments, arguments)
if (length(missing_arguments) > 0) {
	stop(sprintf(
		"wid download_wid API changed; missing arguments: %s",
		paste(missing_arguments, collapse=",")
	))
}

registry <- fromJSON(registry_url, simplifyVector=FALSE)
if (!identical(registry$schema, "kartensammlung.area-registry/v1")) {
	stop(sprintf("Unexpected country registry schema: %s", registry$schema))
}
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
	stop(sprintf("Expected 250 registry ISO2 country codes, got %d", length(registry_codes)))
}
if (!("NA" %in% registry_codes)) {
	stop("Namibia ISO2 code NA is missing from the registry")
}
if (!("XK" %in% registry_codes)) {
	stop("Kosovo ISO2 code XK is missing from the registry")
}

wid_countries <- read.csv(
	wid_countries_url,
	sep=";",
	stringsAsFactors=FALSE,
	check.names=FALSE,
	na.strings=""
)
if (!("alpha2" %in% names(wid_countries))) {
	stop("WID_countries.csv has no alpha2 column")
}
wid_codes <- sort(unique(toupper(trimws(wid_countries$alpha2))))
wid_codes <- wid_codes[!is.na(wid_codes) & grepl("^[A-Z]{2}$", wid_codes)]
if (!("NA" %in% wid_codes)) {
	stop("Namibia ISO2 code NA was lost while parsing WID_countries.csv")
}
if (!("KS" %in% wid_codes)) {
	stop("WID country list no longer contains Kosovo code KS")
}

direct_codes <- intersect(registry_codes, wid_codes)
if (length(direct_codes) != 232) {
	stop(sprintf("Expected 232 direct WID/registry ISO2 overlaps, got %d", length(direct_codes)))
}
if (!("NA" %in% direct_codes)) {
	stop("Namibia must be present in the WID/registry overlap")
}
query_codes <- sort(unique(c(direct_codes, "KS")))
if (length(query_codes) != 233) {
	stop(sprintf("Expected 233 WID query country codes including KS, got %d", length(query_codes)))
}

indicators <- c("sptinc", "shweal")
percentiles <- c("p0p50", "p50p90", "p90p100", "p99p100")
chunks <- split(query_codes, ceiling(seq_along(query_codes) / 40))
pieces <- vector("list", length(chunks))

for (index in seq_along(chunks)) {
	codes <- chunks[[index]]
	cat(sprintf("WID chunk %d/%d countries=%d\n", index, length(chunks), length(codes)))
	pieces[[index]] <- download_wid(
		indicators=indicators,
		areas=codes,
		years="all",
		perc=percentiles,
		ages=992,
		pop="j",
		metadata=FALSE,
		include_extrapolations=TRUE,
		verbose=FALSE
	)
}

pieces <- pieces[!vapply(pieces, is.null, logical(1))]
if (length(pieces) == 0) {
	stop("WID returned no target data")
}
data <- do.call(rbind, pieces)
if (is.null(data) || nrow(data) == 0) {
	stop("WID returned no target rows")
}

required_columns <- c("country", "variable", "percentile", "year", "value")
missing_columns <- setdiff(required_columns, names(data))
if (length(missing_columns) > 0) {
	stop(sprintf("WID response missing columns: %s", paste(missing_columns, collapse=",")))
}

actual_variables <- sort(unique(as.character(data$variable)))
expected_variables <- c("shweal992j", "sptinc992j")
if (!identical(actual_variables, expected_variables)) {
	stop(sprintf("Unexpected WID variables: %s", paste(actual_variables, collapse=",")))
}
actual_percentiles <- sort(unique(as.character(data$percentile)))
if (!identical(actual_percentiles, sort(percentiles))) {
	stop(sprintf("Unexpected WID percentiles: %s", paste(actual_percentiles, collapse=",")))
}
returned_codes <- sort(unique(as.character(data$country)))
unexpected_codes <- setdiff(returned_codes, query_codes)
if (length(unexpected_codes) > 0) {
	stop(sprintf("WID returned unrequested country codes: %s", paste(unexpected_codes, collapse=",")))
}
if (!("KS" %in% returned_codes)) {
	stop("WID returned no Kosovo KS target rows")
}
if (!("NA" %in% returned_codes)) {
	stop("WID returned no Namibia NA target rows")
}

key <- paste(data$country, data$variable, data$percentile, data$year, sep="|")
if (anyDuplicated(key)) {
	stop("WID response contains duplicate country/variable/percentile/year rows")
}

data <- data[order(data$country, data$variable, data$percentile, data$year), required_columns]
dir.create(dirname(output_csv), recursive=TRUE, showWarnings=FALSE)
dir.create(dirname(output_metadata), recursive=TRUE, showWarnings=FALSE)
write.csv(data, output_csv, row.names=FALSE, na="")

coverage_2024 <- aggregate(
	country ~ variable + percentile,
	data=data[data$year == 2024, ],
	FUN=function(values) length(unique(values))
)
if (nrow(coverage_2024) != 8 || any(coverage_2024$country < 216)) {
	stop("WID 2024 target coverage dropped below the audited minimum of 216 countries including KS")
}

metadata <- list(
	retrievedAt=format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz="UTC"),
	package=list(
		name="wid",
		version=actual_version,
		repository="https://github.com/world-inequality-database/wid-r-tool",
		commit=expected_commit
	),
	query=list(
		registryCountries=length(registry_codes),
		directCountryOverlap=length(direct_codes),
		queryCountries=length(query_codes),
		countryAlias=list(KS="XK"),
		age="992",
		population="j",
		years="all",
		includeExtrapolations=TRUE,
		metadata=FALSE,
		series=list(
			list(indicator="sptinc", percentiles=percentiles),
			list(indicator="shweal", percentiles=percentiles)
		)
	),
	rows=nrow(data),
	returnedCountries=length(returned_codes),
	variables=actual_variables,
	percentiles=actual_percentiles,
	coverage2024=coverage_2024
)
write_json(metadata, output_metadata, pretty=TRUE, auto_unbox=TRUE, null="null")

cat(sprintf(
	"WID rows=%d returnedCountries=%d years=%d..%d variables=%s\n",
	nrow(data),
	length(returned_codes),
	min(data$year),
	max(data$year),
	paste(actual_variables, collapse=",")
))
