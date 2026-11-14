import { PageHeader, PhasePlaceholder, Section } from "@/components/ui";

export default function Page() {
  return (
    <>
      <PageHeader title="Agenten" description="Status, letzte Läufe und Kosten aller 18 Agenten." />
      <Section title="Agenten">
        <PhasePlaceholder
          phase="Phase 4"
          items={[
            "Name, Aufgabe und Status je Agent",
            "Letzter Lauf, aktuelle Aufgabe und Ergebnis",
            "Fehlermeldungen und verbrauchte Kosten",
            "Aktivieren und Pausieren einzelner Agenten",
          ]}
        />
      </Section>
    </>
  );
}
