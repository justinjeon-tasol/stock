"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
  ReactNode,
} from "react";
import { supabase } from "@/lib/supabase";
import type { RealtimeChannel } from "@supabase/supabase-js";
import type { MarketPhase, AccountSummary, Position, Trade } from "@/lib/types";

interface RealtimeData {
  marketPhase: MarketPhase | null;
  accountSummary: AccountSummary | null;
  positions: Position[];
  recentTrades: Trade[];
  lastUpdated: {
    marketPhase: Date | null;
    accountSummary: Date | null;
    positions: Date | null;
    trades: Date | null;
  };
  isConnected: boolean;
  refresh: (table?: string) => Promise<void>;
}

const RealtimeContext = createContext<RealtimeData>({
  marketPhase: null,
  accountSummary: null,
  positions: [],
  recentTrades: [],
  lastUpdated: { marketPhase: null, accountSummary: null, positions: null, trades: null },
  isConnected: false,
  refresh: async () => {},
});

export function useSharedRealtime() {
  return useContext(RealtimeContext);
}

export function SharedRealtimeProvider({ children }: { children: ReactNode }) {
  const [marketPhase, setMarketPhase] = useState<MarketPhase | null>(null);
  const [accountSummary, setAccountSummary] = useState<AccountSummary | null>(
    null
  );
  const [positions, setPositions] = useState<Position[]>([]);
  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdated, setLastUpdated] = useState({
    marketPhase: null as Date | null,
    accountSummary: null as Date | null,
    positions: null as Date | null,
    trades: null as Date | null,
  });

  const channelRef = useRef<RealtimeChannel | null>(null);

  const fetchPositions = useCallback(async () => {
    const { data } = await supabase
      .from("positions")
      .select("*")
      .order("entry_time", { ascending: false });
    if (data) {
      setPositions(data as Position[]);
      setLastUpdated((prev) => ({ ...prev, positions: new Date() }));
    }
  }, []);

  const fetchRecentTrades = useCallback(async () => {
    const { data } = await supabase
      .from("trades")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(50);
    if (data) {
      setRecentTrades(data as Trade[]);
      setLastUpdated((prev) => ({ ...prev, trades: new Date() }));
    }
  }, []);

  const fetchInitialData = useCallback(async () => {
    const [phaseRes, accountRes] = await Promise.all([
      supabase
        .from("market_phases")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(1)
        .single(),
      supabase
        .from("account_summary")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(1)
        .single(),
    ]);

    if (phaseRes.data) {
      setMarketPhase(phaseRes.data as MarketPhase);
      setLastUpdated((prev) => ({ ...prev, marketPhase: new Date() }));
    }
    if (accountRes.data) {
      setAccountSummary(accountRes.data as AccountSummary);
      setLastUpdated((prev) => ({ ...prev, accountSummary: new Date() }));
    }

    await fetchPositions();
    await fetchRecentTrades();
  }, [fetchPositions, fetchRecentTrades]);

  const refresh = useCallback(
    async (table?: string) => {
      if (!table || table === "market_phases") {
        const { data } = await supabase
          .from("market_phases")
          .select("*")
          .order("created_at", { ascending: false })
          .limit(1)
          .single();
        if (data) {
          setMarketPhase(data as MarketPhase);
          setLastUpdated((prev) => ({ ...prev, marketPhase: new Date() }));
        }
      }
      if (!table || table === "account_summary") {
        const { data } = await supabase
          .from("account_summary")
          .select("*")
          .order("created_at", { ascending: false })
          .limit(1)
          .single();
        if (data) {
          setAccountSummary(data as AccountSummary);
          setLastUpdated((prev) => ({
            ...prev,
            accountSummary: new Date(),
          }));
        }
      }
      if (!table || table === "positions") {
        await fetchPositions();
      }
      if (!table || table === "trades") {
        await fetchRecentTrades();
      }
    },
    [fetchPositions, fetchRecentTrades]
  );

  useEffect(() => {
    fetchInitialData();

    const channel = supabase
      .channel("dashboard-realtime")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "market_phases" },
        (payload) => {
          setMarketPhase(payload.new as MarketPhase);
          setLastUpdated((prev) => ({ ...prev, marketPhase: new Date() }));
        }
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "account_summary" },
        (payload) => {
          if (payload.new) {
            setAccountSummary(payload.new as AccountSummary);
            setLastUpdated((prev) => ({
              ...prev,
              accountSummary: new Date(),
            }));
          }
        }
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "positions" },
        () => {
          fetchPositions();
        }
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "trades" },
        () => {
          fetchRecentTrades();
        }
      )
      .subscribe((status) => {
        setIsConnected(status === "SUBSCRIBED");
      });

    channelRef.current = channel;

    return () => {
      if (channelRef.current) {
        supabase.removeChannel(channelRef.current);
      }
    };
  }, [fetchInitialData, fetchPositions, fetchRecentTrades]);

  return (
    <RealtimeContext.Provider
      value={{
        marketPhase,
        accountSummary,
        positions,
        recentTrades,
        lastUpdated,
        isConnected,
        refresh,
      }}
    >
      {children}
    </RealtimeContext.Provider>
  );
}
