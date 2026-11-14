import { PageHeader, PhasePlaceholder, Section } from "@/components/ui";

export default function Page() {
  return (
    <>
      <PageHeader title="Kosten" description="Server-, KI-, Speicher- und API-Kosten." />
      <Section title="Kosten">
        <PhasePlaceholder
          phase="Phase 14"
          items={[
            "Server-, KI-, Speicher- und API-Kosten",
            "Monatliche Gesamtkosten im Verhältnis zum Budget",
            "Kosten pro produziertem und veröffentlichtem Video",
            "Kosten pro 1.000 Aufrufe, soweit berechenbar",
          ]}
        />
      </Section>
    </>
  );
}
