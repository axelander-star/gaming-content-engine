import { PageHeader, PhasePlaceholder, Section } from "@/components/ui";

export default function Page() {
  return (
    <>
      <PageHeader title="Publishing" description="Veröffentlichungen je Plattform und Sprache." />
      <Section title="Publishing">
        <PhasePlaceholder
          phase="Phase 11 bis 13"
          items={[
            "YouTube, TikTok, Instagram und Facebook",
            "Deutsche und englische Kanäle",
            "Geplante und fehlgeschlagene Veröffentlichungen",
            "Automatische Veröffentlichungsstrategie je Kanal",
          ]}
        />
      </Section>
    </>
  );
}
