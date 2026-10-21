import {
  activateAdminMode,
  applyAdminResponse,
  buildAdminRequest,
} from "./admin-mode-data.js?v=plan-sentence-redesign";
import {
  activateUserMode,
  applyUserResponse,
  buildUserRequest,
} from "./user-mode-data.js?v=plan-sentence-redesign";

const modeDataAdapters = {
  admin: {
    activate: activateAdminMode,
    buildRequest: (commonFields) => buildAdminRequest(commonFields),
    applyResponse: applyAdminResponse,
  },
  user: {
    activate: activateUserMode,
    buildRequest: buildUserRequest,
    applyResponse: applyUserResponse,
  },
};

export function modeDataFor(mode) {
  const adapter = modeDataAdapters[mode];
  if (!adapter) throw new Error(`지원하지 않는 앱 모드입니다: ${mode || "선택되지 않음"}`);
  return adapter;
}
