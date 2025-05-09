/*
 * Copyright (c) 2022 Huawei Device Co., Ltd.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "launcher.h"
#include "log.h"

namespace OHOS {
void Launcher::InitUI()
{
    rootView_ = RootView::GetInstance();
    rootView_->SetPosition(0, 0, Screen::GetInstance().GetWidth(), Screen::GetInstance().GetHeight());
    HILOG_DEBUG(HILOG_MODULE_APP, "rootView %d-%d", rootView_->GetWidth(), rootView_->GetHeight());

    const int img_x = 25;
    const int img_y = 75;
    const int img_w = 400;
    const int img_h = 300;
    const char LAUNCHER_GIF_PATH[] = "/data/img/launcher.gif";

    gifImageView_ = new UIImageView();
    gifImageView_->SetPosition(img_x, img_y, img_w, img_h);
    gifImageView_->SetSrc(LAUNCHER_GIF_PATH);
    rootView_->Add(gifImageView_);
    rootView_->Invalidate();
}

void Launcher::DeleteUI()
{
    HILOG_DEBUG(HILOG_MODULE_APP, "%s", __func__);
    if (gifImageView_ != nullptr) {
        delete gifImageView_;
        gifImageView_ = nullptr;
    }
}

Launcher::~Launcher()
{
    DeleteUI();
}

void Launcher::OnCreate(const Want &want)
{
    HILOG_DEBUG(HILOG_MODULE_APP, "%s", __func__);
}

void Launcher::OnForeground(const Want &want)
{
    HILOG_DEBUG(HILOG_MODULE_APP, "%s", __func__);
    InitUI();
}

void Launcher::OnBackground()
{
    HILOG_DEBUG(HILOG_MODULE_APP, "%s", __func__);
    DeleteUI();
}

void Launcher::OnDestroy()
{
    HILOG_DEBUG(HILOG_MODULE_APP, "%s", __func__);
    DeleteUI();
}
} // namespace OHOS

extern "C" int InstallNativeAbility(const AbilityInfo *abilityInfo, const OHOS::SliteAbility *ability);
extern "C" void InstallLauncher()
{
    OHOS::Launcher *launcher = OHOS::Launcher::GetInstance();
    InstallNativeAbility(NULL, launcher);
}
