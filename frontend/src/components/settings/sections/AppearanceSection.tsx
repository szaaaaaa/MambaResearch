import React from 'react';
import { Button, Card, Select, Toggle } from '../../ui';
import { UiPreferences } from '../types';

export const AppearanceSection: React.FC<{
  uiPreferences: UiPreferences;
  onUiPreferencesChange: (nextValue: UiPreferences) => void;
}> = ({ uiPreferences, onUiPreferencesChange }) => {
  const [draft, setDraft] = React.useState<UiPreferences>(uiPreferences);

  React.useEffect(() => {
    setDraft(uiPreferences);
  }, [uiPreferences]);

  return (
    <div className="space-y-5">
      <Card title="界面布局" description="这些选项只影响当前前端界面的呈现方式。">
        <div className="grid gap-5 md:grid-cols-2">
          <Select
            label="主题"
            options={[
              { value: 'system', label: '跟随系统' },
              { value: 'light', label: '浅色' },
            ]}
            value={draft.theme}
            onChange={(event) => setDraft((prev) => ({ ...prev, theme: event.target.value as UiPreferences['theme'] }))}
          />
          <Select
            label="界面密度"
            options={[
              { value: 'comfortable', label: '舒适' },
              { value: 'compact', label: '紧凑' },
            ]}
            value={draft.density}
            onChange={(event) =>
              setDraft((prev) => ({ ...prev, density: event.target.value as UiPreferences['density'] }))
            }
          />
          <Select
            label="聊天宽度"
            options={[
              { value: 'standard', label: '标准' },
              { value: 'wide', label: '宽' },
            ]}
            value={draft.chatWidth}
            onChange={(event) =>
              setDraft((prev) => ({ ...prev, chatWidth: event.target.value as UiPreferences['chatWidth'] }))
            }
          />
          <Select
            label="消息字号"
            options={[
              { value: 'base', label: '标准' },
              { value: 'large', label: '稍大' },
            ]}
            value={draft.messageFont}
            onChange={(event) =>
              setDraft((prev) => ({ ...prev, messageFont: event.target.value as UiPreferences['messageFont'] }))
            }
          />
        </div>

        <Toggle
          label="显示欢迎提示"
          description="在空白聊天页展示快速提示语，帮助你更快发起研究。"
          checked={draft.showWelcomeHints}
          onChange={(checked) => setDraft((prev) => ({ ...prev, showWelcomeHints: checked }))}
        />

        <div className="flex justify-end gap-3">
          <Button variant="secondary" onClick={() => setDraft(uiPreferences)}>
            还原
          </Button>
          <Button onClick={() => onUiPreferencesChange(draft)}>应用外观</Button>
        </div>
      </Card>
    </div>
  );
};
