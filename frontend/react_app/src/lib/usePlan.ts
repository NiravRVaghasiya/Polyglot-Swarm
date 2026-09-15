"use client";

// Data hook for the "today's plan" + CEFR profile + insights views. Fetches
// the learner-model endpoints for the authenticated user and exposes
// loading/error state, mirroring useProgress.

import { useCallback, useEffect, useState } from "react";
import { api, CEFRProfile, Insights, PlanResponse } from "./api";

export interface PlanData {
  plan: PlanResponse | null;
  cefr: CEFRProfile | null;
  insights: Insights | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function usePlan(
  token: string | null,
  language?: string,
  opts: { minutes?: number; goal?: string } = {},
): PlanData {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [cefr, setCefr] = useState<CEFRProfile | null>(null);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { minutes, goal } = opts;

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const [p, c, i] = await Promise.all([
        api.todaysPlan(token, { language, minutes, goal }),
        api.cefrProfile(token, language),
        api.insights(token, language),
      ]);
      setPlan(p);
      setCefr(c);
      setInsights(i);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load plan");
    } finally {
      setLoading(false);
    }
  }, [token, language, minutes, goal]);

  useEffect(() => {
    void load();
  }, [load]);

  return { plan, cefr, insights, loading, error, reload: () => void load() };
}
