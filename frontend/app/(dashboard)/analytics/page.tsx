import { PageHeader, PhasePlaceholder, Section } from "@/components/ui";

export default function Page() {
  return (
    <>
      <PageHeader title="Analytics" description="Performance nach Plattform, Sprache, Spiel und Format." />
      <Section title="Analytics">
        <PhasePlaceholder
          phase="Phase 14"
          items={[
            "Filter: Plattform, Sprache, Spiel, Zeitraum, Format, Hook, Zeitpunkt",
            "Aufrufe über Zeit, Zuschauerbindung, Wiedergabedauer",
            "Interaktionsrate und Follower-Wachstum",
            "Performance pro Spiel, Format und Kanal",
          ]}
        />
      </Section>
    </>
  );
}
