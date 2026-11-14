"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import {
  AGENT_STATUS_LABELS,
  BUDGET_LEVEL_LABELS,
  COST_KIND_LABELS,
  RUN_STATUS_LABELS,
  formatDateTime,
  formatEur,
} from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  Agent,
  AgentDecision,
  AgentRun,
  AgentRunStatus,
  AgentStatus,
  Budget,
} from "@/lib/types";

type Tone = "neutral" | "ok" | "warn" | "danger";

const STATUS_TONE: Record<AgentStatus, Tone> = {
  not_available: "neutral",
  stopped: "danger",
  paused: "warn",
  running: "ok",
  error: "danger",
  ready: "ok",
};

const RUN_TONE: Record<AgentRunStatus, Tone> = {
  running: "ok",
  succeeded: "ok",
  failed: "danger",
  skipped: "warn",
};

function statusLabel(a: Agent): string {
  return a.status === "not_available" ? `Folgt in Phase ${a.phase}` : AGENT_STATUS_LABELS[a.status];
}

function summary(data: Record<string, unknown>): string {
  const text = JSON.stringify(data);
  return text === "{}" ? "–" : text.length > 120 ? `${text.slice(0, 117)}…` : text;
}

function RunsTable({ agent, runs }: { agent: Agent; runs: AgentRun[] }) {
  return (
    <Section title={`Letzte Läufe: ${agent.title}`}>
      {runs.length === 0 ? (
        <p className="muted">Noch keine Läufe.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Start</th>
                <th>Status</th>
                <th>Eingabe</th>
                <th>Ergebnis</th>
                <th>Kosten</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{formatDateTime(r.started_at)}</td>
                  <td>
                    <Badge tone={RUN_TONE[r.status]}>{RUN_STATUS_LABELS[r.status]}</Badge>
                  </td>
                  <td className="small mono">{summary(r.input)}</td>
                  <td className="small mono">{r.error ?? summary(r.output)}</td>
                  <td>{formatEur(r.cost_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function DecisionsList({
  decisions,
  titles,
}: {
  decisions: AgentDecision[];
  titles: Map<string, string>;
}) {
  return (
    <Section title="Letzte Entscheidungen">
      <p className="muted small">
        Jede wichtige Entscheidung eines Agenten wird mit Begründung gespeichert.
      </p>
      {decisions.length === 0 ? (
        <p className="muted">Noch keine Entscheidungen protokolliert.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Zeit</th>
                <th>Agent</th>
                <th>Art</th>
                <th>Begründung</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((d) => (
                <tr key={d.id}>
                  <td>{formatDateTime(d.created_at)}</td>
                  <td>{titles.get(d.agent_name) ?? d.agent_name}</td>
                  <td>{d.decision_type}</td>
                  <td className="small">{d.reasoning ?? summary(d.decision)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

export function AgentsView() {
  const { user } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [selected, setSelected] = useState<string>("master");
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b, d] = await Promise.all([api.agents(), api.budget(), api.agentDecisions()]);
      setAgents(a);
      setBudget(b);
      setDecisions(d);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    api
      .agentRuns(selected)
      .then(setRuns)
      .catch((e: Error) => setError(e.message));
  }, [selected, agents]);

  if (!user) return null;
  const isAdmin = hasRole(user.role, "admin");
  const isOperator = hasRole(user.role, "operator");
  const titles = new Map(agents.map((a) => [a.name, a.title]));
  const implemented = agents.filter((a) => a.implemented).length;
  const master = agents.find((a) => a.name === "master");
  const selectedAgent = agents.find((a) => a.name === selected);

  async function act(action: () => Promise<unknown>, message: string) {
    try {
      await action();
      setNotice(message);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Agenten"
        description="Status, letzte Läufe, Entscheidungen und Kosten aller 18 Agenten."
      />
      <div className="grid stats">
        <StatCard
          label="Aktive Agenten"
          value={`${implemented} / ${agents.length || 18}`}
          hint="Weitere Agenten folgen mit ihren Phasen"
        />
        <StatCard
          label="Budget diesen Monat"
          value={budget ? `${formatEur(budget.spent_eur)} / ${formatEur(budget.budget_eur)}` : "–"}
          hint={
            budget ? `${budget.used_pct} % · Stufe ${BUDGET_LEVEL_LABELS[budget.level]}` : undefined
          }
        />
        <StatCard
          label="Kostenpflichtige Aufrufe"
          value={budget?.paid_api_calls_enabled ? "Erlaubt" : "Gesperrt"}
          hint="Nur nach ausdrücklicher Freigabe"
        />
        <StatCard
          label="Master Orchestrator"
          value={master ? AGENT_STATUS_LABELS[master.status] : "–"}
          hint={
            master?.last_run_at
              ? `Letzter Lauf ${formatDateTime(master.last_run_at)}`
              : "Noch kein Lauf"
          }
        />
      </div>
      <ErrorText error={error} />
      {notice && (
        <p className="ok" role="status">
          {notice}
        </p>
      )}
      <Section title="Alle Agenten">
        {isAdmin && (
          <div className="form-actions">
            {agents
              .filter((a) => a.can_run_manually)
              .map((a) => (
                <button
                  key={a.name}
                  type="button"
                  className="btn btn-primary"
                  disabled={a.status === "stopped" || a.status === "paused"}
                  onClick={() =>
                    void act(() => api.runAgent(a.name), `${a.title} wurde gestartet.`)
                  }
                >
                  {a.title} jetzt ausführen
                </button>
              ))}
          </div>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nr.</th>
                <th>Agent</th>
                <th>Status</th>
                <th>Letzter Lauf</th>
                <th>Läufe heute</th>
                <th>Kosten (Monat)</th>
                <th>Steuerung</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.name} className={a.name === selected ? "selected" : undefined}>
                  <td>{a.number}</td>
                  <td>
                    <button type="button" className="link-btn" onClick={() => setSelected(a.name)}>
                      {a.title}
                    </button>
                    <div className="muted small">
                      {a.description} · {COST_KIND_LABELS[a.cost_kind]}
                    </div>
                    {a.current_task && (
                      <div className="small mono">Aufgabe: {summary(a.current_task)}</div>
                    )}
                    {a.last_error && <div className="error small">{a.last_error}</div>}
                  </td>
                  <td>
                    <Badge tone={STATUS_TONE[a.status]}>{statusLabel(a)}</Badge>
                  </td>
                  <td>
                    {formatDateTime(a.last_run_at)}
                    {a.last_run_status && (
                      <div className="muted small">{RUN_STATUS_LABELS[a.last_run_status]}</div>
                    )}
                  </td>
                  <td>{a.runs_today}</td>
                  <td>{formatEur(a.cost_month_eur)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      aria-label={`${a.title} ${a.enabled ? "pausieren" : "fortsetzen"}`}
                      disabled={a.enabled ? !isOperator : !isAdmin}
                      title={a.enabled ? "Agent pausieren" : "Nur Admins können fortsetzen"}
                      onClick={() =>
                        void act(
                          () => (a.enabled ? api.pauseAgent(a.name) : api.resumeAgent(a.name)),
                          `${a.title} wurde ${a.enabled ? "pausiert" : "fortgesetzt"}.`,
                        )
                      }
                    >
                      {a.enabled ? "Pausieren" : "Fortsetzen"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      {selectedAgent && <RunsTable agent={selectedAgent} runs={runs} />}
      <DecisionsList decisions={decisions} titles={titles} />
    </>
  );
}
