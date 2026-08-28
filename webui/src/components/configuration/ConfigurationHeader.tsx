export function ConfigurationHeader({
  backLabel,
  onBack,
}: {
  backLabel: string;
  onBack: () => void;
}) {
  return (
    <div className="configuration-back-row">
      <button className="configuration-back" type="button" onClick={onBack}>
        {backLabel}
      </button>
    </div>
  );
}
