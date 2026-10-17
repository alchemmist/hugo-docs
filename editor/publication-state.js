import {t} from './i18n.js';

export function createPublicationState(button) {
  let generation = 0;
  return {
    reset() { generation++; button.textContent = t("Publish"); },
    pending() {
      const token = ++generation;
      button.textContent = t("Saved · publishing…");
      return published => {
        if (token === generation) button.textContent = published ? t("Published") : t("Saved · publication failed");
      };
    }
  };
}
