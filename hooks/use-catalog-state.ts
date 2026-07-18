"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DEFAULT_COLUMNS, DEFAULT_FILTERS } from "@/types/catalog";
import type { CatalogState, ColumnKey, SortKey } from "@/types/catalog";

const PAGE_SIZES = new Set([25, 50, 100]);
const SORT_KEYS = new Set(["source", "name", "category", "price-low", "price-high"]);
const COLUMN_KEYS = new Set(["name", "capacity", "category", "price", "etc", "manufacturer", "image"]);
const NOTE_FILTERS = new Set(["all", "with", "without"]);
const OFFICIAL_FILTERS = new Set([
  "all",
  "confirmed",
  "not_found",
  "not_applicable",
  "review_required",
  "linked",
  "unlinked",
]);
const IMAGE_FILTERS = new Set(["all", "with", "without"]);

function positiveNumber(value: string | null) {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function list(value: string | null) {
  return value?.split(",").map((item) => item.trim()).filter(Boolean) ?? [];
}

function allowed<T extends string>(value: string | null, choices: Set<string>, fallback: T): T {
  return value && choices.has(value) ? value as T : fallback;
}

function defaults(): CatalogState {
  return {
    ...DEFAULT_FILTERS,
    sort: "source" as SortKey,
    cols: [...DEFAULT_COLUMNS],
    page: 1,
    pageSize: 50,
    product: "",
  } as CatalogState;
}

function readState(): CatalogState {
  const base = defaults();
  if (typeof window === "undefined") return base;
  const params = new URLSearchParams(window.location.search);
  const requestedPageSize = positiveInteger(params.get("pageSize"), 50);
  const requestedColumns = [...new Set(list(params.get("cols")).filter((column) => COLUMN_KEYS.has(column)))] as ColumnKey[];
  const columns = requestedColumns.length ? requestedColumns : [...base.cols];
  if (!columns.includes("name")) columns.unshift("name");

  return {
    ...base,
    q: params.get("q") ?? base.q,
    categories: list(params.get("categories")),
    priceMin: positiveNumber(params.get("priceMin")),
    priceMax: positiveNumber(params.get("priceMax")),
    note: allowed(params.get("note"), NOTE_FILTERS, "all"),
    official: allowed(params.get("official"), OFFICIAL_FILTERS, "all"),
    image: allowed(params.get("image"), IMAGE_FILTERS, "all"),
    sort: allowed(params.get("sort"), SORT_KEYS, base.sort),
    cols: columns,
    page: positiveInteger(params.get("page"), 1),
    pageSize: PAGE_SIZES.has(requestedPageSize) ? requestedPageSize : 50,
    product: params.get("product") ?? "",
  } as CatalogState;
}

function writeState(state: CatalogState) {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams();
  const set = (key: string, value: unknown, fallback?: unknown) => {
    if (value === undefined || value === null || value === "" || value === fallback) return;
    params.set(key, String(value));
  };

  set("q", state.q);
  if (state.categories?.length) params.set("categories", state.categories.join(","));
  set("priceMin", state.priceMin);
  set("priceMax", state.priceMax);
  set("note", state.note, "all");
  set("official", state.official, "all");
  set("image", state.image, "all");
  set("sort", state.sort, "source");
  if (state.cols?.join(",") !== DEFAULT_COLUMNS.join(",")) params.set("cols", state.cols.join(","));
  set("page", state.page, 1);
  set("pageSize", state.pageSize, 50);
  set("product", state.product);

  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
}

export function useCatalogState() {
  const [state, setStateValue] = useState<CatalogState>(defaults);
  const hydrated = useRef(false);

  useEffect(() => {
    const sync = () => setStateValue(readState());
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  useEffect(() => {
    if (!hydrated.current) {
      hydrated.current = true;
      return;
    }
    writeState(state);
  }, [state]);

  const setState = useCallback((patch: Partial<CatalogState> | ((current: CatalogState) => Partial<CatalogState>)) => {
    setStateValue((current) => {
      const nextPatch = typeof patch === "function" ? patch(current) : patch;
      return { ...current, ...nextPatch } as CatalogState;
    });
  }, []);

  const resetFilters = useCallback(() => {
    setState((current) => ({
      ...DEFAULT_FILTERS,
      sort: current.sort,
      cols: current.cols,
      page: 1,
    }));
  }, [setState]);

  return { state, setState, resetFilters };
}

export type CatalogStateUpdater = ReturnType<typeof useCatalogState>["setState"];
