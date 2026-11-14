import { PageHeader, PhasePlaceholder, Section } from "@/components/ui";

export default function Page() {
  return (
    <>
      <PageHeader title="Videoproduktion" description="Material, Szenen, Clips und Renderjobs." />
      <Section title="Videoproduktion">
        <PhasePlaceholder
          phase="Phase 7 bis 10"
          items={[
            "Eingehendes Material und erkannte Szenen",
            "Ausgewählte Clips und aktuelle Renderjobs",
            "Deutsche und englische Versionen",
            "Qualitätsstatus, freigegebene und fehlerhafte Videos",
          ]}
        />
      </Section>
    </>
  );
}
