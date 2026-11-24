<template>
  <div class="workflow-editor-shell">
    <header class="workflow-topbar">
      <div class="workflow-title-group">
        <div class="workflow-brand-mark">P</div>
        <div>
          <div class="workflow-brand">AgentFlow</div>
          <a-input
            v-model:value="workflowName"
            class="workflow-name-input"
            placeholder="工作流名称"
            :bordered="false"
          />
        </div>
        <a-select v-model:value="engineType" class="workflow-engine-select" :options="engineOptions" />
      </div>

      <div class="workflow-actions">
        <LLMConfigModal />
        <a-button @click="navigate('/knowledge')">
          <template #icon><DatabaseOutlined /></template>
          知识库
        </a-button>
        <a-button @click="navigate('/mcp-tools')">
          <template #icon><ApiOutlined /></template>
          MCP 工具
        </a-button>
        <a-button @click="handleCreateNew">
          <template #icon><PlusOutlined /></template>
          新建
        </a-button>
        <a-button @click="handleOpenLoadModal">
          <template #icon><FolderOpenOutlined /></template>
          加载
        </a-button>
        <a-button type="primary" :loading="saving" @click="handleSave">
          <template #icon><SaveOutlined /></template>
          保存
        </a-button>
        <a-button :disabled="!activeWorkflowId" @click="handleOpenDebug">
          <template #icon><BugOutlined /></template>
          调试
        </a-button>
        <div class="workflow-user">
          <span class="workflow-user-name">{{ username }}</span>
          <a-button type="text" size="small" @click="handleLogout">
            <template #icon><LogoutOutlined /></template>
            登出
          </a-button>
        </div>
      </div>
    </header>

    <div class="workflow-workbench">
      <aside class="workflow-left-panel">
        <NodePanel @drag-start="handleDragStart" @add-node="handleAddNode" />
      </aside>

      <main class="workflow-canvas-panel">
        <FlowCanvas ref="canvasRef" @node-click="handleNodeClick" />
      </main>

      <aside class="workflow-config-panel">
        <div class="workflow-panel-heading">
          <div>
            <p class="workflow-panel-kicker">Inspector</p>
            <h3>节点配置</h3>
          </div>
          <span v-if="selectedNode" class="workflow-node-pill">{{ selectedNodeType || 'node' }}</span>
        </div>

        <div v-if="selectedNode" class="workflow-config-body">
          <div class="workflow-selected-card">
            <div class="workflow-selected-icon">{{ selectedNodeLabel.slice(0, 1).toUpperCase() }}</div>
            <div class="min-w-0">
              <p class="workflow-selected-title">{{ selectedNodeLabel }}</p>
              <p class="workflow-selected-meta">{{ selectedNode.id }}</p>
            </div>
          </div>

          <a-form v-if="selectedNode.data?.type === 'input'" layout="vertical" class="workflow-config-form">
            <a-form-item label="变量名">
              <a-input value="user_input" disabled />
            </a-form-item>
            <a-form-item label="变量类型">
              <a-input value="String" disabled />
            </a-form-item>
            <a-form-item label="描述">
              <a-textarea value="用户本轮的输入内容" disabled :rows="2" />
            </a-form-item>
            <a-form-item label="是否必要">
              <a-checkbox :checked="true" disabled>必要</a-checkbox>
            </a-form-item>
          </a-form>

          <a-form v-if="selectedNode.data?.type === 'output'" layout="vertical" class="workflow-config-form">
            <div class="workflow-config-section">
              <div class="workflow-config-section-header">
                <label class="font-medium text-gray-700">输出配置</label>
                <a-button type="dashed" size="small" @click="handleAddOutputParam">
                  <template #icon><PlusOutlined /></template>
                  添加
                </a-button>
              </div>

              <div v-for="(param, index) in outputParams" :key="index" class="workflow-param-row">
                <div>
                  <a-input
                    placeholder="参数名"
                    :value="param.name"
                    style="width: 100px"
                    @change="handleUpdateOutputParam(index, 'name', inputValue($event))"
                  />
                </div>
                <div>
                  <a-select
                    :value="param.type"
                    style="width: 80px"
                    @change="(value: any) => handleUpdateOutputParam(index, 'type', String(value))"
                  >
                    <a-select-option value="input">输入</a-select-option>
                    <a-select-option value="reference">引用</a-select-option>
                  </a-select>
                </div>
                <div class="flex-1">
                  <a-input
                    v-if="param.type === 'input'"
                    placeholder="输入值"
                    :value="param.value"
                    @change="handleUpdateOutputParam(index, 'value', inputValue($event))"
                  />
                  <a-select
                    v-else
                    placeholder="选择参数"
                    :value="param.referenceNode"
                    class="w-full workflow-reference-select"
                    :dropdown-match-select-width="false"
                    :dropdown-style="{ minWidth: 360 }"
                    @change="(value: any) => handleUpdateOutputParam(index, 'referenceNode', String(value ?? ''))"
                  >
                    <a-select-option v-for="p in getReferenceableParams()" :key="p.value" :value="p.value" :title="p.label">
                      {{ p.label }}
                    </a-select-option>
                  </a-select>
                </div>
                <a-button type="text" danger size="small" @click="handleRemoveOutputParam(index)">
                  <template #icon><DeleteOutlined /></template>
                </a-button>
              </div>

              <div v-if="outputParams.length === 0" class="workflow-config-empty">
                点击"添加"按钮添加输出参数
              </div>
            </div>

            <a-form-item label="回答内容配置">
              <a-textarea
                v-model:value="responseContent"
                :rows="6"
                placeholder="使用 {{参数名}} 引用输出配置中的参数"
              />
              <div class="workflow-field-hint">
                <span v-pre>💡 提示: 使用 {{ 参数名 }} 引用上面定义的参数</span>
              </div>
            </a-form-item>

            <a-button type="primary" block @click="handleSaveOutputConfig">保存配置</a-button>
          </a-form>

          <a-form v-if="isLlmNodeType(selectedNodeType)" layout="vertical" class="workflow-config-form">
            <div class="workflow-config-section">
              <div class="workflow-config-section-header">
                <label class="font-medium text-gray-700">输入参数</label>
                <a-button type="dashed" size="small" @click="handleAddLlmInputParam">
                  <template #icon><PlusOutlined /></template>
                  添加
                </a-button>
              </div>

              <div v-for="(param, index) in llmInputParams" :key="index" class="workflow-param-row">
                <a-input
                  placeholder="参数名"
                  :value="param.name"
                  style="width: 90px"
                  @change="handleUpdateLlmInputParam(index, 'name', inputValue($event))"
                />
                <a-select
                  :value="param.type"
                  style="width: 70px"
                  @change="(value: any) => handleUpdateLlmInputParam(index, 'type', String(value))"
                >
                  <a-select-option value="input">输入</a-select-option>
                  <a-select-option value="reference">引用</a-select-option>
                </a-select>
                <div class="flex-1">
                  <a-input
                    v-if="param.type === 'input'"
                    placeholder="输入值"
                    :value="param.value"
                    @change="handleUpdateLlmInputParam(index, 'value', inputValue($event))"
                  />
                  <a-select
                    v-else
                    placeholder="选择参数"
                    :value="param.referenceNode"
                    class="w-full workflow-reference-select"
                    :dropdown-match-select-width="false"
                    :dropdown-style="{ minWidth: 360 }"
                    @change="(value: any) => handleUpdateLlmInputParam(index, 'referenceNode', String(value ?? ''))"
                  >
                    <a-select-option v-for="p in getReferenceableParams()" :key="p.value" :value="p.value" :title="p.label">
                      {{ p.label }}
                    </a-select-option>
                  </a-select>
                </div>
                <a-button type="text" danger size="small" @click="handleRemoveLlmInputParam(index)">
                  <template #icon><DeleteOutlined /></template>
                </a-button>
              </div>

              <div v-if="llmInputParams.length === 0" class="workflow-config-empty">
                点击"添加"按钮添加输入参数
              </div>
            </div>

            <div class="workflow-config-section">
              <div class="workflow-config-section-header">
                <label class="font-medium text-gray-700">输出参数</label>
                <a-button type="dashed" size="small" @click="handleAddLlmOutputParam">
                  <template #icon><PlusOutlined /></template>
                  添加
                </a-button>
              </div>

              <div v-for="(param, index) in llmOutputParams" :key="index" class="workflow-param-row">
                <a-input
                  placeholder="变量名"
                  :value="param.name"
                  style="width: 100px"
                  @change="handleUpdateLlmOutputParam(index, 'name', inputValue($event))"
                />
                <a-input value="string" disabled style="width: 70px" />
                <div class="flex-1">
                  <a-input
                    placeholder="描述（可选）"
                    :value="param.description"
                    @change="handleUpdateLlmOutputParam(index, 'description', inputValue($event))"
                  />
                </div>
                <a-button type="text" danger size="small" @click="handleRemoveLlmOutputParam(index)">
                  <template #icon><DeleteOutlined /></template>
                </a-button>
              </div>

              <div v-if="llmOutputParams.length === 0" class="workflow-config-empty">
                点击"添加"按钮添加输出参数
              </div>
            </div>

            <a-form-item label="提示词模板" required>
              <a-textarea
                v-model:value="llmConfig.prompt"
                :rows="12"
                placeholder="输入提示词模板，使用 {{参数名}} 引用输入参数"
                style="font-family: monospace; font-size: 12px"
              />
              <div class="workflow-field-hint">
                <span v-pre>💡 使用 {{ 参数名 }} 引用上面定义的输入参数</span>
              </div>
            </a-form-item>

            <a-form-item v-if="isGenericLlmNode" label="Agent策略">
              <a-select :value="llmConfig.agentStrategy" @change="handleAgentStrategyChange">
                <a-select-option value="none">普通大模型调用</a-select-option>
                <a-select-option value="react">ReAct（支持 Tools）</a-select-option>
              </a-select>
            </a-form-item>

            <a-form-item v-if="isReActMode" label="最大 ReAct 步数">
              <a-input
                type="number"
                min="1"
                max="20"
                :value="llmConfig.maxSteps"
                @change="llmConfig.maxSteps = clampInt(inputValue($event), 1, 20, 5)"
              />
              <div class="workflow-field-hint">
                每一步只能做一次工具调用或给出最终答案，超过步数会停止执行
              </div>
            </a-form-item>

            <a-form-item v-if="isReActMode" label="工具列表">
              <a-checkbox-group
                :value="llmConfig.tools"
                :options="agentToolOptions"
                @change="(values: any) => (llmConfig.tools = (values as string[]).map(String))"
              />
              <div class="workflow-field-hint">
                写入记忆用于让 ReAct 在需要时保存稳定结论。
              </div>
            </a-form-item>

            <a-form-item v-if="isReActMode" label="MCP 工具">
              <a-select
                v-model:value="llmConfig.mcpToolIds"
                mode="multiple"
                placeholder="选择当前大模型节点可调用的 MCP 工具"
                allow-clear
                :options="mcpToolOptions"
              />
              <div class="workflow-field-hint">
                MCP 工具作为大模型节点的可选工具组件使用；可在顶部“MCP 工具”中添加 Agent Plan 联网搜索。
              </div>
            </a-form-item>

            <div class="workflow-config-section">
              <div class="workflow-config-section-title">上下文能力</div>
              <a-form-item>
                <a-checkbox v-model:checked="llmConfig.memoryEnabled">启用记忆召回</a-checkbox>
                <div class="workflow-field-hint">
                  记忆是大模型节点的上下文能力：执行此节点前召回相关记忆，注入到当前提示词。
                </div>
              </a-form-item>
              <a-form-item v-if="llmConfig.memoryEnabled" label="记忆 TopK">
                <a-input
                  type="number"
                  min="1"
                  max="20"
                  :value="llmConfig.memoryTopK"
                  @change="llmConfig.memoryTopK = clampInt(inputValue($event), 1, 20, 5)"
                />
              </a-form-item>
              <a-form-item label="知识库">
                <a-select
                  :value="llmConfig.knowledgeBaseId"
                  placeholder="选择知识库作为当前大模型节点的 RAG 上下文"
                  allow-clear
                  :options="knowledgeBaseOptions"
                  @change="handleKnowledgeBaseChange"
                />
                <div class="workflow-field-hint">
                  知识库作为大模型节点的可选组件使用；可在顶部“知识库”中创建、导入文本并建立索引。
                </div>
              </a-form-item>
              <template v-if="llmConfig.knowledgeBaseId">
                <a-form-item label="知识库 TopK">
                  <a-input
                    type="number"
                    min="1"
                    max="20"
                    :value="llmConfig.knowledgeTopK"
                    @change="llmConfig.knowledgeTopK = clampInt(inputValue($event), 1, 20, 5)"
                  />
                </a-form-item>
                <a-form-item label="最低相关度">
                  <a-input
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    :value="llmConfig.knowledgeScoreThreshold"
                    @change="llmConfig.knowledgeScoreThreshold = clampFloat(inputValue($event), 1, 0)"
                  />
                </a-form-item>
              </template>
            </div>

            <a-form-item label="全局配置" :required="!llmConfig.configId && !llmConfig.apiUrl">
              <a-select
                :value="llmConfig.configId"
                placeholder="选择一个全局配置"
                allow-clear
                @change="handleLlmConfigSelect"
              >
                <a-select-option v-for="config in availableLlmConfigs" :key="config.id" :value="config.id">
                  {{ isGenericLlmNode ? getGlobalConfigLabel(config) : config.model }}
                </a-select-option>
              </a-select>
              <div class="workflow-field-hint">
                💡 选择全局配置后无需填写下方 API 信息
              </div>
            </a-form-item>

            <template v-if="!llmConfig.configId">
              <a-form-item v-if="isGenericLlmNode" label="供应商" required>
                <a-select
                  :value="llmConfig.provider || undefined"
                  placeholder="选择这条节点配置要使用的供应商"
                  :options="providerOptions"
                  @change="(value: any) => (llmConfig.provider = String(value))"
                />
              </a-form-item>
              <div class="workflow-config-warning">
                ⚠️ 未选择全局配置，请手动填写以下 API 信息
              </div>
              <a-form-item label="API 地址" required>
                <a-input
                  v-model:value="llmConfig.apiUrl"
                  placeholder="例如: https://dashscope.aliyuncs.com/compatible-mode"
                />
                <div class="workflow-field-hint">
                  填写兼容接口根地址，不要追加 <code>/v1</code> 或 <code>/v1/chat/completions</code>
                </div>
              </a-form-item>
              <a-form-item label="API 密钥" required>
                <a-input-password v-model:value="llmConfig.apiKey" placeholder="输入 API Key" />
              </a-form-item>
              <a-form-item label="模型名称" required>
                <a-input
                  v-model:value="llmConfig.model"
                  placeholder="例如: deepseek-chat, claude-3-5-sonnet-20241022"
                />
              </a-form-item>
            </template>

            <a-form-item label="温度">
              <a-input
                type="number"
                step="0.1"
                min="0"
                max="2"
                :value="llmConfig.temperature"
                @change="llmConfig.temperature = clampFloat(inputValue($event), 2, 0.7)"
              />
              <div class="workflow-field-hint">
                控制当前节点输出随机性，范围 0-2，值越高越随机
              </div>
            </a-form-item>

            <div v-if="llmConfig.configId" class="workflow-config-summary">
              <div class="font-medium mb-2">当前使用全局配置：</div>
              <div>供应商: {{ getProviderLabel(llmConfig.provider) }}</div>
              <div>API 地址: {{ llmConfig.apiUrl }}</div>
              <div>模型: {{ llmConfig.model }}</div>
            </div>

            <a-form-item label="技能 (Skill)">
              <SkillSelector v-model="llmConfig.skillName" />
              <div class="workflow-field-hint">
                选择一个技能来增强 LLM 的能力，LLM 会自动获取技能指南
              </div>
            </a-form-item>
            <a-button type="primary" block @click="handleSaveLlmConfig">保存配置</a-button>
          </a-form>

          <a-form v-if="selectedNode.data?.type === 'tts'" layout="vertical" class="workflow-config-form">
            <div class="workflow-config-section">
              <div class="workflow-config-section-header">
                <label class="font-medium text-gray-700">输入配置</label>
                <a-button type="dashed" size="small" @click="handleAddTtsInputParam">
                  <template #icon><PlusOutlined /></template>
                  添加
                </a-button>
              </div>

              <div v-for="(param, index) in ttsInputParams" :key="index" class="mb-4 p-3 bg-gray-50 rounded">
                <div class="workflow-param-row is-compact">
                  <a-input
                    placeholder="参数名 (如: text)"
                    :value="param.name"
                    :style="{ width: '120px' }"
                    @change="handleUpdateTtsInputParam(index, 'name', inputValue($event))"
                  />
                  <a-select
                    :value="param.type"
                    :style="{ width: '100px' }"
                    @change="(value: any) => handleUpdateTtsInputParam(index, 'type', String(value))"
                  >
                    <a-select-option value="input">输入</a-select-option>
                    <a-select-option value="reference">引用</a-select-option>
                  </a-select>
                  <a-button type="text" danger @click="handleRemoveTtsInputParam(index)">
                    <template #icon><DeleteOutlined /></template>
                  </a-button>
                </div>
                <div>
                  <a-textarea
                    v-if="param.type === 'input'"
                    placeholder="输入值"
                    :value="param.value"
                    :rows="2"
                    @change="handleUpdateTtsInputParam(index, 'value', inputValue($event))"
                  />
                  <a-select
                    v-else
                    placeholder="选择引用参数"
                    :value="param.referenceNode"
                    class="workflow-reference-select"
                    :dropdown-match-select-width="false"
                    :dropdown-style="{ minWidth: 360 }"
                    style="width: 100%"
                    @change="(value: any) => handleUpdateTtsInputParam(index, 'referenceNode', String(value ?? ''))"
                  >
                    <a-select-option v-for="p in getReferenceableParams()" :key="p.value" :value="p.value" :title="p.label">
                      {{ p.label }}
                    </a-select-option>
                  </a-select>
                </div>
              </div>

              <div v-if="ttsInputParams.length === 0" class="workflow-config-empty">
                暂无输入参数,点击"添加"按钮创建 text 参数
              </div>
            </div>

            <div class="workflow-config-section">
              <label class="workflow-config-section-title">基本信息</label>
              <a-form-item label="全局配置" :required="!ttsConfig.configId && !ttsConfig.apiUrl">
                <a-select
                  :value="ttsConfig.configId"
                  placeholder="选择一个通义千问或阶跃星辰配置"
                  allow-clear
                  @change="handleTtsConfigSelect"
                >
                  <a-select-option v-for="config in availableTtsConfigs" :key="config.id" :value="config.id">
                    {{ getGlobalConfigLabel(config) }}
                  </a-select-option>
                </a-select>
                <div class="workflow-field-hint">
                  选择全局配置后无需在节点中保存 API Key。
                </div>
              </a-form-item>

              <template v-if="!ttsConfig.configId">
                <a-form-item label="供应商" required>
                  <a-select
                    :value="ttsConfig.provider"
                    :options="ttsProviderOptions"
                    @change="handleTtsProviderChange"
                  />
                </a-form-item>
                <div class="workflow-config-warning">
                  ⚠️ 未选择全局配置，请手动填写以下 API 信息
                </div>
                <a-form-item label="API 地址" required>
                  <a-input
                    v-model:value="ttsConfig.apiUrl"
                    :placeholder="isStepTtsProvider ? 'https://api.stepfun.com/v1' : 'https://dashscope.aliyuncs.com/api/v1'"
                  />
                </a-form-item>
                <a-form-item label="API Key" required>
                  <a-input-password
                    v-model:value="ttsConfig.apiKey"
                    :placeholder="isStepTtsProvider ? '请输入 StepFun API Key' : '请输入阿里百炼 API Key'"
                  />
                </a-form-item>
                <a-form-item label="模型名称" required>
                  <a-input
                    v-model:value="ttsConfig.model"
                    :placeholder="isStepTtsProvider ? 'stepaudio-2.5-tts' : 'qwen3-tts-flash'"
                  />
                </a-form-item>
              </template>

              <div v-if="ttsConfig.configId" class="workflow-config-summary">
                <div class="font-medium mb-2">当前使用全局配置：</div>
                <div>供应商: {{ getProviderLabel(ttsConfig.provider) }}</div>
                <div>API 地址: {{ ttsConfig.apiUrl }}</div>
                <div>模型: {{ ttsConfig.model }}</div>
              </div>
            </div>

            <div class="workflow-config-section">
              <label class="workflow-config-section-title">语音参数</label>
              <div v-if="!hasTtsProvider" class="workflow-config-empty">
                请先选择全局配置或手动选择供应商。
              </div>
              <div v-else class="space-y-3">
                <a-form-item label="音色 (voice)" class="mb-0">
                  <a-input
                    v-if="isStepTtsProvider"
                    placeholder="例如: cixingnansheng"
                    :value="ttsConfig.voice"
                    @change="ttsConfig.voice = inputValue($event)"
                  />
                  <a-select
                    v-else
                    show-search
                    :value="ttsConfig.voice || undefined"
                    @change="(value: any) => (ttsConfig.voice = String(value))"
                  >
                    <a-select-option value="Cherry">Cherry (芊悦)</a-select-option>
                    <a-select-option value="Serena">Serena (苏瑶)</a-select-option>
                    <a-select-option value="Ethan">Ethan (晨煦)</a-select-option>
                    <a-select-option value="Chelsie">Chelsie (千雪)</a-select-option>
                    <a-select-option value="Momo">Momo (茉兔)</a-select-option>
                    <a-select-option value="Vivian">Vivian (十三)</a-select-option>
                    <a-select-option value="Moon">Moon (月白)</a-select-option>
                    <a-select-option value="Maia">Maia (四月)</a-select-option>
                    <a-select-option value="Kai">Kai (凯)</a-select-option>
                    <a-select-option value="Nofish">Nofish (不吃鱼)</a-select-option>
                    <a-select-option value="Bella">Bella (萌宝)</a-select-option>
                    <a-select-option value="Jennifer">Jennifer (詹妮弗)</a-select-option>
                    <a-select-option value="Ryan">Ryan (甜茶)</a-select-option>
                    <a-select-option value="Katerina">Katerina (卡捷琳娜)</a-select-option>
                    <a-select-option value="Aiden">Aiden (艾登)</a-select-option>
                  </a-select>
                </a-form-item>

                <a-form-item v-if="!isStepTtsProvider" label="语言类型 (language_type)" class="mb-0">
                  <a-select :value="ttsConfig.languageType" @change="(value: any) => (ttsConfig.languageType = String(value))">
                    <a-select-option value="Auto">Auto</a-select-option>
                  </a-select>
                </a-form-item>

                <template v-if="isStepTtsProvider">
                  <a-form-item label="全局语境 (instruction)" class="mb-0" :help="`${ttsConfig.instruction.length}/200`">
                    <a-textarea
                      v-model:value="ttsConfig.instruction"
                      :rows="3"
                      :maxlength="200"
                      placeholder="例如: 语气紧张，语速偏快，带明显压迫感"
                    />
                  </a-form-item>
                  <a-form-item label="语速 (speed)" class="mb-0">
                    <a-input
                      type="number"
                      step="0.1"
                      min="0.5"
                      max="2"
                      :value="ttsConfig.speed"
                      @change="ttsConfig.speed = clampFloat(inputValue($event), 2, 1)"
                    />
                  </a-form-item>
                  <a-form-item label="音量 (volume)" class="mb-0">
                    <a-input
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="2"
                      :value="ttsConfig.volume"
                      @change="ttsConfig.volume = clampFloat(inputValue($event), 2, 1)"
                    />
                  </a-form-item>
                  <a-form-item label="采样率 (sample_rate)" class="mb-0">
                    <a-select :value="ttsConfig.sampleRate" @change="(value: any) => (ttsConfig.sampleRate = Number(value))">
                      <a-select-option :value="8000">8000</a-select-option>
                      <a-select-option :value="16000">16000</a-select-option>
                      <a-select-option :value="22050">22050</a-select-option>
                      <a-select-option :value="24000">24000</a-select-option>
                      <a-select-option :value="48000">48000</a-select-option>
                    </a-select>
                  </a-form-item>
                </template>
              </div>
            </div>

            <div class="workflow-config-section">
              <div class="workflow-config-section-header">
                <label class="font-medium text-gray-700">输出配置</label>
                <a-button type="dashed" size="small" @click="handleAddTtsOutputParam">
                  <template #icon><PlusOutlined /></template>
                  添加
                </a-button>
              </div>

              <div v-for="(param, index) in ttsOutputParams" :key="index" class="workflow-param-row">
                <a-input
                  placeholder="参数名 (如: voice_url)"
                  :value="param.name"
                  :style="{ flex: 1 }"
                  @change="handleUpdateTtsOutputParam(index, 'name', inputValue($event))"
                />
                <a-input
                  placeholder="参数值 (引用字段,如: audioUrl)"
                  :value="param.value"
                  :style="{ flex: 1 }"
                  @change="handleUpdateTtsOutputParam(index, 'value', inputValue($event))"
                />
                <a-button type="text" danger @click="handleRemoveTtsOutputParam(index)">
                  <template #icon><DeleteOutlined /></template>
                </a-button>
              </div>

              <div v-if="ttsOutputParams.length === 0" class="workflow-config-empty">
                暂无输出参数,点击"添加"按钮创建 voice_url 参数
              </div>
            </div>

            <a-button type="primary" block @click="handleSaveTtsConfig">保存配置</a-button>
          </a-form>

          <a-form v-if="isAgentPlanNode" layout="vertical" class="workflow-config-form">
            <a-form-item :label="agentPlanConfigLabel">
              <a-select
                :value="(selectedNode.data?.configId as number) || undefined"
                :placeholder="agentPlanConfigPlaceholder"
                allow-clear
                @change="handleToolConfigSelect"
              >
                <a-select-option v-for="config in availableToolConfigs" :key="config.id" :value="config.id">
                  {{ getGlobalConfigLabel(config) }}
                </a-select-option>
              </a-select>
            </a-form-item>

            <template v-if="!selectedNode.data?.configId">
              <a-form-item v-if="selectedNodeType === 'image_generate'" label="供应商">
                <a-select
                  :value="selectedToolProvider"
                  :options="imageGenerationProviderOptions"
                  @change="handleImageProviderChange"
                />
              </a-form-item>
              <a-form-item label="API 地址">
                <a-input
                  :placeholder="agentPlanApiUrlPlaceholder"
                  :value="(selectedNode.data?.apiUrl as string) || ''"
                  @change="handleAgentPlanApiUrlInput"
                />
              </a-form-item>
              <a-form-item label="API Key">
                <a-input-password
                  :value="(selectedNode.data?.apiKey as string) || ''"
                  @change="updateSelectedNodeData({ apiKey: inputValue($event) })"
                />
              </a-form-item>
              <a-form-item label="模型覆盖">
                <a-input
                  :placeholder="agentPlanModelPlaceholder"
                  :value="(selectedNode.data?.model as string) || ''"
                  @change="handleAgentPlanModelInput"
                />
              </a-form-item>
            </template>

            <template v-if="selectedNodeType === 'web_search'">
              <a-form-item label="搜索问题">
                <a-textarea
                  :rows="3"
                  :value="(selectedNode.data?.query as string) || ''"
                  @change="updateSelectedNodeData({ query: inputValue($event) })"
                />
              </a-form-item>
              <a-form-item label="结果数量">
                <a-input
                  type="number"
                  min="1"
                  max="10"
                  :value="(selectedNode.data?.limit as number) || 5"
                  @change="updateSelectedNodeData({ limit: parseInt(inputValue($event), 10) || 5 })"
                />
              </a-form-item>
            </template>

            <a-form-item v-if="selectedNodeType === 'web_fetch'" label="URL 列表">
              <a-textarea
                :rows="4"
                placeholder="多个 URL 可用换行分隔"
                :value="(selectedNode.data?.urls as string) || ''"
                @change="updateSelectedNodeData({ urls: inputValue($event) })"
              />
            </a-form-item>

            <template v-if="['memory_write', 'knowledge_upsert'].includes(selectedNodeType)">
              <a-form-item v-if="selectedNodeType === 'knowledge_upsert'" label="知识库">
                <a-select
                  :value="(selectedNode.data?.knowledgeBaseId as string) || undefined"
                  placeholder="选择知识库，未选择时写入默认知识库"
                  allow-clear
                  :options="knowledgeBaseOptions"
                  @change="(value: any) => updateSelectedNodeData({ knowledgeBaseId: value || 'default' })"
                />
                <div class="workflow-field-hint">
                  可在顶部“知识库”中创建、导入文本并建立索引。
                </div>
              </a-form-item>
              <a-form-item :label="selectedNodeType === 'memory_write' ? '记忆内容' : '知识内容'">
                <a-textarea
                  :rows="5"
                  :value="(selectedNode.data?.content as string) || ''"
                  @change="updateSelectedNodeData({ content: inputValue($event) })"
                />
              </a-form-item>
              <a-form-item label="标签">
                <a-input
                  placeholder="多个标签用逗号分隔"
                  :value="(selectedNode.data?.tags as string) || ''"
                  @change="updateSelectedNodeData({ tags: inputValue($event) })"
                />
              </a-form-item>
            </template>

            <template v-if="['memory_retrieve', 'knowledge_retrieve'].includes(selectedNodeType)">
              <a-form-item v-if="selectedNodeType === 'knowledge_retrieve'" label="知识库">
                <a-select
                  :value="(selectedNode.data?.knowledgeBaseId as string) || undefined"
                  placeholder="选择要检索的知识库"
                  allow-clear
                  :options="knowledgeBaseOptions"
                  @change="(value: any) => updateSelectedNodeData({ knowledgeBaseId: value || 'default' })"
                />
              </a-form-item>
              <a-form-item label="召回问题">
                <a-textarea
                  :rows="3"
                  :value="(selectedNode.data?.query as string) || ''"
                  @change="updateSelectedNodeData({ query: inputValue($event) })"
                />
              </a-form-item>
              <a-form-item label="TopK">
                <a-input
                  type="number"
                  min="1"
                  max="20"
                  :value="(selectedNode.data?.topK as number) || 5"
                  @change="updateSelectedNodeData({ topK: parseInt(inputValue($event), 10) || 5 })"
                />
              </a-form-item>
            </template>

            <template v-if="selectedNodeType === 'image_generate'">
              <div class="workflow-config-section">
                <div class="workflow-config-section-header">
                  <label class="font-medium text-gray-700">输入配置</label>
                  <a-button type="dashed" size="small" @click="addAgentPlanInputParam('prompt')">
                    <template #icon><PlusOutlined /></template>
                    添加
                  </a-button>
                </div>
                <div v-for="(param, index) in getAgentPlanInputParams()" :key="index" class="mb-4 p-3 bg-gray-50 rounded">
                  <div class="workflow-param-row is-compact">
                    <a-input
                      placeholder="参数名"
                      :value="param.name"
                      :style="{ width: '120px' }"
                      @change="updateAgentPlanInputParam(index, 'name', inputValue($event))"
                    />
                    <a-select
                      :value="param.type"
                      :style="{ width: '100px' }"
                      @change="(value: any) => updateAgentPlanInputParam(index, 'type', String(value))"
                    >
                      <a-select-option value="input">输入</a-select-option>
                      <a-select-option value="reference">引用</a-select-option>
                    </a-select>
                    <a-button type="text" danger @click="removeAgentPlanInputParam(index)">
                      <template #icon><DeleteOutlined /></template>
                    </a-button>
                  </div>
                  <div>
                    <a-textarea
                      v-if="param.type === 'input'"
                      placeholder="输入值"
                      :value="param.value"
                      :rows="2"
                      @change="updateAgentPlanInputParam(index, 'value', inputValue($event))"
                    />
                    <a-select
                      v-else
                      placeholder="选择引用参数"
                      :value="param.referenceNode"
                      class="workflow-reference-select"
                      :dropdown-match-select-width="false"
                      :dropdown-style="{ minWidth: 360 }"
                      style="width: 100%"
                      @change="(value: any) => updateAgentPlanInputParam(index, 'referenceNode', String(value ?? ''))"
                    >
                      <a-select-option v-for="p in getReferenceableParams()" :key="p.value" :value="p.value" :title="p.label">
                        {{ p.label }}
                      </a-select-option>
                    </a-select>
                  </div>
                </div>
                <div v-if="getAgentPlanInputParams().length === 0" class="workflow-config-empty">
                  暂无输入参数，点击"添加"创建 prompt 引用。
                </div>
              </div>
              <a-form-item label="原图">
                <div class="workflow-param-row">
                  <a-input
                    class="flex-1"
                    placeholder="粘贴需要改造的原图 URL，或上传一张原图"
                    :value="(selectedNode.data?.referenceImageUrl as string) || ''"
                    @change="updateSelectedNodeData({ referenceImageUrl: inputValue($event) })"
                  />
                  <a-upload accept="image/*" :show-upload-list="false" :before-upload="beforeUploadImage">
                    <a-button>
                      <template #icon><UploadOutlined /></template>
                      上传原图
                    </a-button>
                  </a-upload>
                </div>
                <div v-if="selectedNode.data?.referenceImageUrl" class="workflow-reference-image-preview">
                  <img :src="selectedNode.data.referenceImageUrl as string" alt="参考图预览" />
                </div>
                <div class="workflow-field-hint">
                  填入或上传原图后，图片生成会按图生图执行；留空则按文生图执行。参考风格、构图等要求请写在提示词里。
                </div>
              </a-form-item>
              <a-form-item label="尺寸">
                <a-select
                  v-if="selectedToolProvider === 'step'"
                  :value="(selectedNode.data?.size as string) || getDefaultStepImageSize(selectedImageModel)"
                  :options="stepImageSizeOptions"
                  @change="(value: any) => updateSelectedNodeData({ size: String(value) })"
                />
                <a-input
                  v-else
                  placeholder="2K"
                  :value="(selectedNode.data?.size as string) || '2K'"
                  @change="updateSelectedNodeData({ size: inputValue($event) })"
                />
              </a-form-item>
              <template v-if="selectedToolProvider === 'step'">
                <a-form-item label="生成步数">
                  <a-input
                    type="number"
                    min="1"
                    max="50"
                    :value="(selectedNode.data?.steps as number) || (isStepImageEditModel ? 8 : 50)"
                    @change="updateSelectedNodeData({ steps: parseInt(inputValue($event), 10) || (isStepImageEditModel ? 8 : 50) })"
                  />
                </a-form-item>
                <a-form-item label="提示词遵循度">
                  <a-input
                    type="number"
                    step="0.1"
                    min="1"
                    max="10"
                    :value="(selectedNode.data?.cfgScale as number) || (isStepImageEditModel ? 1 : 7.5)"
                    @change="updateSelectedNodeData({ cfgScale: parseFloat(inputValue($event)) || (isStepImageEditModel ? 1 : 7.5) })"
                  />
                </a-form-item>
                <a-form-item label="随机种子">
                  <a-input
                    type="number"
                    placeholder="可选；为空时随机"
                    :value="(selectedNode.data?.seed as number) || undefined"
                    @change="updateSelectedNodeData({ seed: inputValue($event) ? parseInt(inputValue($event), 10) : undefined })"
                  />
                </a-form-item>
                <template v-if="isStepImageEditModel">
                  <a-form-item label="文字优化模式">
                    <a-checkbox
                      :checked="(selectedNode.data?.textMode as boolean | undefined) ?? true"
                      @change="updateSelectedNodeData({ textMode: checkedValue($event) })"
                    >
                      开启
                    </a-checkbox>
                  </a-form-item>
                  <a-form-item label="负面约束">
                    <a-textarea
                      :rows="2"
                      placeholder="例如：低清晰度、变形、多余文字、水印、Logo"
                      :value="(selectedNode.data?.negativePrompt as string) || ''"
                      @change="updateSelectedNodeData({ negativePrompt: inputValue($event) })"
                    />
                  </a-form-item>
                </template>
              </template>
              <div class="workflow-config-section">
                <div class="workflow-config-section-header">
                  <label class="font-medium text-gray-700">输出配置</label>
                  <a-button type="dashed" size="small" @click="addAgentPlanOutputParam('image_url', 'imageUrl')">
                    <template #icon><PlusOutlined /></template>
                    添加
                  </a-button>
                </div>
                <div v-for="(param, index) in getAgentPlanOutputParams()" :key="index" class="workflow-param-row">
                  <a-input
                    placeholder="输出名，如 image_url"
                    :value="param.name"
                    :style="{ flex: 1 }"
                    @change="updateAgentPlanOutputParam(index, 'name', inputValue($event))"
                  />
                  <a-select
                    placeholder="来源字段"
                    :value="param.value || undefined"
                    :style="{ flex: 1 }"
                    :options="imageOutputFieldOptions"
                    @change="(value: any) => updateAgentPlanOutputParam(index, 'value', String(value))"
                  />
                  <a-button type="text" danger @click="removeAgentPlanOutputParam(index)">
                    <template #icon><DeleteOutlined /></template>
                  </a-button>
                </div>
                <div v-if="getAgentPlanOutputParams().length === 0" class="workflow-config-empty">
                  默认输出 imageUrl、imageUrls、prompt、output；点击"添加"可映射成自定义输出名。
                </div>
              </div>
            </template>

            <template v-if="selectedNodeType === 'video_generate'">
              <div class="workflow-config-section">
                <div class="workflow-config-section-header">
                  <label class="font-medium text-gray-700">输入配置</label>
                  <a-button type="dashed" size="small" @click="addAgentPlanInputParam('prompt')">
                    <template #icon><PlusOutlined /></template>
                    添加
                  </a-button>
                </div>
                <div v-for="(param, index) in getAgentPlanInputParams()" :key="index" class="mb-4 p-3 bg-gray-50 rounded">
                  <div class="workflow-param-row is-compact">
                    <a-input
                      placeholder="参数名"
                      :value="param.name"
                      :style="{ width: '120px' }"
                      @change="updateAgentPlanInputParam(index, 'name', inputValue($event))"
                    />
                    <a-select
                      :value="param.type"
                      :style="{ width: '100px' }"
                      @change="(value: any) => updateAgentPlanInputParam(index, 'type', String(value))"
                    >
                      <a-select-option value="input">输入</a-select-option>
                      <a-select-option value="reference">引用</a-select-option>
                    </a-select>
                    <a-button type="text" danger @click="removeAgentPlanInputParam(index)">
                      <template #icon><DeleteOutlined /></template>
                    </a-button>
                  </div>
                  <div>
                    <a-textarea
                      v-if="param.type === 'input'"
                      placeholder="输入值"
                      :value="param.value"
                      :rows="2"
                      @change="updateAgentPlanInputParam(index, 'value', inputValue($event))"
                    />
                    <a-select
                      v-else
                      placeholder="选择引用参数"
                      :value="param.referenceNode"
                      class="workflow-reference-select"
                      :dropdown-match-select-width="false"
                      :dropdown-style="{ minWidth: 360 }"
                      style="width: 100%"
                      @change="(value: any) => updateAgentPlanInputParam(index, 'referenceNode', String(value ?? ''))"
                    >
                      <a-select-option v-for="p in getReferenceableParams()" :key="p.value" :value="p.value" :title="p.label">
                        {{ p.label }}
                      </a-select-option>
                    </a-select>
                  </div>
                </div>
                <div v-if="getAgentPlanInputParams().length === 0" class="workflow-config-empty">
                  暂无输入参数，点击"添加"创建 prompt 引用。
                </div>
              </div>
              <a-form-item label="首帧">
                <div class="workflow-param-row">
                  <a-input
                    class="flex-1"
                    placeholder="粘贴用于图生视频的首帧 URL，或上传一张首帧图"
                    :value="(selectedNode.data?.referenceImageUrl as string) || ''"
                    @change="updateSelectedNodeData({ referenceImageUrl: inputValue($event) })"
                  />
                  <a-upload accept="image/*" :show-upload-list="false" :before-upload="beforeUploadImage">
                    <a-button>
                      <template #icon><UploadOutlined /></template>
                      上传首帧
                    </a-button>
                  </a-upload>
                </div>
                <div v-if="selectedNode.data?.referenceImageUrl" class="workflow-reference-image-preview">
                  <img :src="selectedNode.data.referenceImageUrl as string" alt="首帧预览" />
                </div>
                <div class="workflow-field-hint">
                  填入或上传首帧后，视频生成会按图生视频执行；留空则按文生视频执行。
                </div>
              </a-form-item>
              <a-form-item label="时长(秒)">
                <a-input
                  type="number"
                  :value="(selectedNode.data?.duration as number) || 5"
                  @change="updateSelectedNodeData({ duration: parseInt(inputValue($event), 10) || 5 })"
                />
              </a-form-item>
              <div class="workflow-config-section">
                <div class="workflow-config-section-header">
                  <label class="font-medium text-gray-700">输出配置</label>
                  <a-button type="dashed" size="small" @click="addAgentPlanOutputParam('video_url', 'videoUrl')">
                    <template #icon><PlusOutlined /></template>
                    添加
                  </a-button>
                </div>
                <div v-for="(param, index) in getAgentPlanOutputParams()" :key="index" class="workflow-param-row">
                  <a-input
                    placeholder="输出名，如 video_url"
                    :value="param.name"
                    :style="{ flex: 1 }"
                    @change="updateAgentPlanOutputParam(index, 'name', inputValue($event))"
                  />
                  <a-select
                    placeholder="来源字段"
                    :value="param.value || undefined"
                    :style="{ flex: 1 }"
                    :options="videoOutputFieldOptions"
                    @change="(value: any) => updateAgentPlanOutputParam(index, 'value', String(value))"
                  />
                  <a-button type="text" danger @click="removeAgentPlanOutputParam(index)">
                    <template #icon><DeleteOutlined /></template>
                  </a-button>
                </div>
                <div v-if="getAgentPlanOutputParams().length === 0" class="workflow-config-empty">
                  默认输出 videoUrl、coverUrl、taskId、status、output；点击"添加"可映射成自定义输出名。
                </div>
              </div>
            </template>
          </a-form>

          <div
            v-if="selectedNode.data?.type !== 'input' && selectedNode.data?.type !== 'output' && !isLlmNodeType(selectedNodeType) && selectedNode.data?.type !== 'tts' && !isAgentPlanNode"
            class="workflow-config-empty"
          >
            该节点暂无可配置项
          </div>
        </div>

        <div v-else class="workflow-empty-inspector">
          <div class="workflow-empty-icon">+</div>
          <p>未选择节点</p>
        </div>
      </aside>
    </div>

    <DebugDrawer
      :open="debugDrawerOpen"
      :workflow-id="activeWorkflowId"
      :total-node-count="nodes.length"
      @close="debugDrawerOpen = false"
    />

    <a-modal
      title="加载工作流"
      :open="loadModalOpen"
      :footer="null"
      :width="600"
      @cancel="loadModalOpen = false"
    >
      <a-list :loading="loadingWorkflows" :data-source="workflows">
        <template #renderItem="{ item: workflow }">
          <a-list-item>
            <template #actions>
              <a-button type="link" @click="handleLoadWorkflow(workflow)">加载</a-button>
              <a-popconfirm
                title="删除工作流"
                :description="`确定删除「${workflow.name}」吗?`"
                ok-text="删除"
                cancel-text="取消"
                :ok-button-props="{ danger: true, loading: deletingWorkflowId === workflow.id }"
                @confirm="handleDeleteWorkflow(workflow)"
              >
                <a-button danger type="link" :loading="deletingWorkflowId === workflow.id">
                  <template #icon><DeleteOutlined /></template>
                  删除
                </a-button>
              </a-popconfirm>
            </template>
            <a-list-item-meta
              :title="workflow.name"
              :description="`创建于: ${new Date(workflow.createdAt).toLocaleString()}`"
            />
          </a-list-item>
        </template>
      </a-list>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiOutlined,
  BugOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  PlusOutlined,
  SaveOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import { MarkerType } from '@vue-flow/core'
import type { Edge, Node } from '@vue-flow/core'
import NodePanel from '../components/NodePanel.vue'
import FlowCanvas from '../components/FlowCanvas.vue'
import SkillSelector from '../components/SkillSelector.vue'
import LLMConfigModal from '../components/LLMConfigModal.vue'
import { logout } from '../api/auth'
import { useWorkflowStore } from '../stores/workflow'
import { useAuthStore } from '../stores/auth'
import { useLLMConfigStore } from '../stores/llmConfig'
import {
  createWorkflow,
  deleteWorkflow,
  getWorkflow,
  getWorkflows,
  updateWorkflow,
  type Workflow,
} from '../api/workflow'
import { getKnowledgeBases, type KnowledgeBase } from '../api/knowledge'
import { getMcpTools, type McpToolConfig } from '../api/mcpTools'
import { uploadWorkflowImage } from '../api/media'
import { getRefreshToken } from '../utils/auth'
import {
  getProviderFromNodeType,
  getProviderLabel,
  getSupportedProviderOptions,
  isLlmNodeType,
  normalizeProviderKey,
} from '../utils/provider'
import {
  createDefaultWorkflowNodes,
  normalizeWorkflowNodes,
  serializeWorkflowNodes,
} from '../utils/workflowNode'

const DebugDrawer = defineAsyncComponent(() => import('../components/DebugDrawer.vue'))

interface OutputParam {
  name: string
  type: 'input' | 'reference'
  value: string
  referenceNode?: string
}

interface LlmInputParam {
  name: string
  type: 'input' | 'reference'
  value: string
  referenceNode?: string
}

interface LlmOutputParam {
  name: string
  type: string
  description?: string
}

interface TtsInputParam {
  name: string
  type: 'input' | 'reference'
  value: string
  referenceNode?: string
}

interface TtsOutputParam {
  name: string
  value: string
}

interface WorkflowCanvasData {
  nodes?: Node[]
  edges?: Edge[]
}

const normalizeAgentToolSelection = (tools: string[]) => {
  const normalized = new Set<string>()
  tools.forEach((tool) => {
    if (tool === 'memory_retrieve') return
    if (tool === 'web_search' || tool === 'web_fetch') return
    normalized.add(tool)
  })
  return Array.from(normalized)
}

const expandAgentToolSelection = (tools: string[]) => {
  const expanded = new Set<string>()
  tools.forEach((tool) => {
    if (tool === 'memory_retrieve') return
    expanded.add(tool)
    if (tool === 'web_search') {
      expanded.add('web_fetch')
    }
  })
  return Array.from(expanded)
}

const normalizeStringArray = (value: unknown) => {
  if (!Array.isArray(value)) return []
  return value.map(String).filter(Boolean)
}

const enrichKnowledgeBaseNames = (nodes: Node[], knowledgeBases: KnowledgeBase[]) => {
  if (knowledgeBases.length === 0) return nodes
  const nameById = new Map(knowledgeBases.map((base) => [String(base.id), base.name]))
  let changed = false
  const nextNodes = nodes.map((node) => {
    const knowledgeBaseId = node.data?.knowledgeBaseId
    if (typeof knowledgeBaseId !== 'string') return node
    const knowledgeBaseName = nameById.get(knowledgeBaseId)
    if (!knowledgeBaseName || node.data?.knowledgeBaseName === knowledgeBaseName) return node
    changed = true
    return {
      ...node,
      data: {
        ...node.data,
        knowledgeBaseName,
      },
    }
  })
  return changed ? nextNodes : nodes
}

const router = useRouter()
const route = useRoute()
const navigate = (path: string) => router.push(path)

const authStore = useAuthStore()
const { username } = storeToRefs(authStore)

const workflowStore = useWorkflowStore()
const { nodes, edges, selectedNode, currentWorkflowId } = storeToRefs(workflowStore)
const { setNodes, setEdges, setCurrentWorkflowId } = workflowStore

const llmConfigStore = useLLMConfigStore()
const { configs: llmGlobalConfigs } = storeToRefs(llmConfigStore)
const fetchLLMGlobalConfigs = llmConfigStore.fetchAllConfigs

const workflowName = ref('未命名工作流')
const engineType = ref('dag')
const saving = ref(false)
const debugDrawerOpen = ref(false)
const outputParams = ref<OutputParam[]>([])
const responseContent = ref('')
const loadModalOpen = ref(false)
const workflows = ref<Workflow[]>([])
const loadingWorkflows = ref(false)
const deletingWorkflowId = ref<number | null>(null)
const knowledgeBases = ref<KnowledgeBase[]>([])
const mcpTools = ref<McpToolConfig[]>([])
const canvasRef = ref<{ addNode: (type: string, label?: string) => void } | null>(null)
const hasLoadedRef = ref<number | null>(null)
const autoSaveTimerRef = ref<number | null>(null)

const engineOptions = [
  { value: 'dag', label: 'DAG 引擎' },
  { value: 'langgraph', label: 'LangGraph 引擎' },
]

const routeWorkflowId = computed(() => {
  const value = route.params.id
  const raw = Array.isArray(value) ? value[0] : value
  return raw ? Number.parseInt(raw, 10) : null
})

const activeWorkflowId = computed(() =>
  routeWorkflowId.value !== null && Number.isFinite(routeWorkflowId.value)
    ? routeWorkflowId.value
    : currentWorkflowId.value
)

const llmConfig = reactive({
  provider: '',
  configId: undefined as number | undefined,
  apiUrl: '',
  apiKey: '',
  model: '',
  temperature: 0.7,
  prompt: '',
  skillName: '',
  maxSteps: 5,
  agentStrategy: 'none',
  tools: [] as string[],
  memoryEnabled: false,
  memoryTopK: 5,
  mcpToolIds: [] as string[],
  knowledgeBaseId: undefined as string | undefined,
  knowledgeBaseName: '',
  knowledgeTopK: 5,
  knowledgeScoreThreshold: 0.2,
})

const llmInputParams = ref<LlmInputParam[]>([])
const llmOutputParams = ref<LlmOutputParam[]>([])

const ttsConfig = reactive({
  provider: '',
  configId: undefined as number | undefined,
  apiUrl: '',
  apiKey: '',
  model: '',
  voice: '',
  languageType: 'Auto',
  instruction: '',
  speed: 1,
  volume: 1,
  sampleRate: 24000,
})

const ttsInputParams = ref<TtsInputParam[]>([])
const ttsOutputParams = ref<TtsOutputParam[]>([])

const inputValue = (event: Event) => (event.target as HTMLInputElement).value
const checkedValue = (event: unknown) =>
  Boolean((event as { target?: { checked?: boolean } })?.target?.checked)

const clampInt = (raw: string, min: number, max: number, fallback: number) => {
  const parsed = Number.parseInt(raw, 10)
  if (Number.isNaN(parsed)) return fallback
  return Math.min(max, Math.max(min, parsed))
}

const clampFloat = (raw: string, max: number, fallback: number) => {
  const parsed = Number.parseFloat(raw)
  if (Number.isNaN(parsed)) return fallback
  return Math.min(max, Math.max(0, parsed))
}

const resolveSelectedNodeProvider = (node: Node | null) => {
  if (!node) {
    return ''
  }

  const configuredProvider = normalizeProviderKey(String(node.data?.provider || ''))
  if (configuredProvider) {
    return configuredProvider
  }

  return getProviderFromNodeType(String(node.data?.type || ''))
}

const getDefaultTtsModel = (provider: string) =>
  provider === 'step' ? 'stepaudio-2.5-tts' : provider === 'qwen' ? 'qwen3-tts-flash' : ''

const getDefaultTtsVoice = (provider: string) =>
  provider === 'step' ? 'cixingnansheng' : provider === 'qwen' ? 'Cherry' : ''

const getTtsModelForProvider = (
  provider: string,
  ttsModel?: string | null,
  fallbackModel?: string | null
) => {
  const normalizedProvider = normalizeProviderKey(provider)
  const explicitTtsModel = ttsModel?.trim() || ''
  if (explicitTtsModel) {
    return explicitTtsModel
  }

  const trimmedModel = fallbackModel?.trim() || ''
  const lowerModel = trimmedModel.toLowerCase()

  if (normalizedProvider === 'step') {
    return lowerModel.includes('step') && lowerModel.includes('tts')
      ? trimmedModel
      : getDefaultTtsModel(normalizedProvider)
  }

  if (normalizedProvider === 'qwen') {
    return lowerModel.includes('tts') ? trimmedModel : getDefaultTtsModel(normalizedProvider)
  }

  return trimmedModel
}

const getGlobalConfigLabel = (config: {
  provider: string
  model?: string
  ttsModel?: string
  imageModel?: string
  videoModel?: string
}) => {
  const providerLabel = getProviderLabel(config.provider)
  const modelLabel = config.model ? `LLM: ${config.model}` : ''
  const ttsModelLabel = config.ttsModel ? `TTS: ${config.ttsModel}` : ''
  const imageModelLabel = config.imageModel ? `生图: ${config.imageModel}` : ''
  const videoModelLabel = config.videoModel ? `生视频: ${config.videoModel}` : ''
  return [providerLabel, modelLabel, ttsModelLabel, imageModelLabel, videoModelLabel]
    .filter(Boolean)
    .join(' / ')
}

const getDefaultStepImageSize = (model?: string) =>
  model === 'step-image-edit-2' ? '768x1360' : '1280x800'

const providerOptions = computed(() =>
  Array.from(
    new Map(
      [
        ...getSupportedProviderOptions(),
        ...llmGlobalConfigs.value.map((config) => {
          const provider = normalizeProviderKey(config.provider)
          return {
            value: provider,
            label: getProviderLabel(provider),
          }
        }),
      ].map((option) => [option.value, option])
    ).values()
  )
)

const buildRuntimeToolSelection = (tools: string[], mcpToolIds: string[]) => {
  const selected = new Set(expandAgentToolSelection(tools))
  mcpTools.value
    .filter((tool) => mcpToolIds.includes(String(tool.id)))
    .forEach((tool) => {
      if (tool.toolName) {
        selected.add(tool.toolName)
      }
      if (tool.toolName === 'web_search') {
        selected.add('web_fetch')
      }
    })
  return Array.from(selected)
}

const handleDragStart = (event: DragEvent, nodeType: string, displayName: string) => {
  event.dataTransfer?.setData('application/reactflow-type', nodeType)
  event.dataTransfer?.setData('application/reactflow-label', displayName)
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
  }
}

const handleAddNode = (nodeType: string, displayName: string) => {
  canvasRef.value?.addNode(nodeType, displayName)
}

const handleNodeClick = (node: Node) => {
  if (autoSaveTimerRef.value) {
    clearTimeout(autoSaveTimerRef.value)
    autoSaveTimerRef.value = null
  }

  workflowStore.setSelectedNode(node)

  if (node.data?.type === 'output') {
    outputParams.value = (node.data?.outputParams as OutputParam[]) || []
    responseContent.value = (node.data?.responseContent as string) || ''
  } else if (isLlmNodeType(String(node.data?.type || ''))) {
    const configId = (node.data?.configId as number) || undefined
    const matchedGlobalConfig = configId
      ? llmGlobalConfigs.value.find((c) => c.id === configId)
      : undefined
    const provider = normalizeProviderKey(
      matchedGlobalConfig?.provider ||
        String(node.data?.provider || '') ||
        getProviderFromNodeType(String(node.data?.type || ''))
    )
    Object.assign(llmConfig, {
      provider,
      configId,
      apiUrl: matchedGlobalConfig?.apiUrl || (node.data?.apiUrl as string) || '',
      apiKey: configId ? '' : (node.data?.apiKey as string) || '',
      model: matchedGlobalConfig?.model || (node.data?.model as string) || '',
      temperature: (node.data?.temperature as number) || 0.7,
      prompt: (node.data?.prompt as string) || '',
      skillName: (node.data?.skillName as string) || '',
      maxSteps: (node.data?.maxSteps as number) || 5,
      agentStrategy:
        (node.data?.agentStrategy as string) || (node.data?.type === 'react_agent' ? 'react' : 'none'),
      tools: normalizeAgentToolSelection(
        Array.isArray(node.data?.tools) ? (node.data.tools as string[]) : []
      ),
      memoryEnabled: Boolean(node.data?.memoryEnabled),
      memoryTopK: (node.data?.memoryTopK as number) || 5,
      mcpToolIds: normalizeStringArray(node.data?.mcpToolIds),
      knowledgeBaseId: (node.data?.knowledgeBaseId as string) || undefined,
      knowledgeBaseName: (node.data?.knowledgeBaseName as string) || '',
      knowledgeTopK: (node.data?.knowledgeTopK as number) || 5,
      knowledgeScoreThreshold: (node.data?.knowledgeScoreThreshold as number) || 0.2,
    })
    llmInputParams.value = (node.data?.inputParams as LlmInputParam[]) || []
    llmOutputParams.value = (node.data?.outputParams as LlmOutputParam[]) || []
  } else if (node.data?.type === 'tts') {
    const configId = (node.data?.configId as number) || undefined
    const matchedGlobalConfig = configId
      ? llmGlobalConfigs.value.find((c) => c.id === configId)
      : undefined
    const provider = normalizeProviderKey(
      matchedGlobalConfig?.provider ||
        String(node.data?.provider || '') ||
        (String(node.data?.model || '').toLowerCase().includes('step') ? 'step' : '')
    )
    Object.assign(ttsConfig, {
      provider,
      configId,
      apiUrl: matchedGlobalConfig?.apiUrl || (node.data?.apiUrl as string) || '',
      apiKey: configId ? '' : (node.data?.apiKey as string) || '',
      model: getTtsModelForProvider(
        provider,
        matchedGlobalConfig?.ttsModel,
        matchedGlobalConfig?.model || (node.data?.model as string)
      ),
      voice:
        (node.data?.voice as string) ||
        (provider === 'step' ? 'cixingnansheng' : provider === 'qwen' ? 'Cherry' : ''),
      languageType: (node.data?.languageType as string) || 'Auto',
      instruction: (node.data?.instruction as string) || '',
      speed: (node.data?.speed as number) || 1,
      volume: (node.data?.volume as number) || 1,
      sampleRate: (node.data?.sampleRate as number) || 24000,
    })
    ttsInputParams.value = (node.data?.inputParams as TtsInputParam[]) || []
    ttsOutputParams.value = (node.data?.outputParams as TtsOutputParam[]) || []
  }
}

const loadWorkflowById = async (workflowId: number) => {
  try {
    const result = await getWorkflow(workflowId)
    if (result.code === 200) {
      const workflow = result.data
      workflowName.value = workflow.name
      engineType.value = workflow.engineType || 'dag'
      setCurrentWorkflowId(workflow.id)

      const flowData = JSON.parse(workflow.flowData) as WorkflowCanvasData

      const loadedNodes = enrichKnowledgeBaseNames(
        normalizeWorkflowNodes(flowData.nodes || []),
        knowledgeBases.value
      )
      setNodes(loadedNodes)

      const loadedEdges = (flowData.edges || []).map((edge) => ({
        ...edge,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 20,
          height: 20,
        },
      }))
      setEdges(loadedEdges)

      const outputNode = loadedNodes.find((node) => node.data?.type === 'output')
      const rawOutputParams = outputNode?.data?.outputParams
      const rawResponseContent = outputNode?.data?.responseContent
      outputParams.value = Array.isArray(rawOutputParams) ? (rawOutputParams as OutputParam[]) : []
      responseContent.value = typeof rawResponseContent === 'string' ? rawResponseContent : ''

      message.success('工作流加载成功')
    }
  } catch {
    message.error('工作流加载失败')
  }
}

const handleSave = async () => {
  if (nodes.value.length === 0) {
    message.warning('工作流为空,无法保存')
    return
  }

  const flowData = JSON.stringify({
    nodes: serializeWorkflowNodes(nodes.value),
    edges: edges.value.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
    })),
  })

  saving.value = true
  try {
    if (currentWorkflowId.value) {
      await updateWorkflow(currentWorkflowId.value, {
        name: workflowName.value,
        flowData,
        engineType: engineType.value,
      })
      message.success('工作流保存成功')
    } else {
      const result = await createWorkflow({
        name: workflowName.value,
        description: '通过编辑器创建',
        flowData,
        engineType: engineType.value,
      })
      if (result.code === 200) {
        const workflowId = result.data.id
        setCurrentWorkflowId(workflowId)
        router.replace(`/editor/${workflowId}`)
        message.success('工作流创建成功')
      }
    }
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

const handleOpenDebug = () => {
  if (!activeWorkflowId.value) {
    message.warning('请先保存工作流')
    return
  }
  debugDrawerOpen.value = true
}

const handleLogout = async () => {
  const refreshToken = getRefreshToken()
  if (refreshToken) {
    try {
      await logout({ refreshToken })
    } catch {
      // 后端退出失败不阻塞本地登出
    }
  }
  authStore.clearAuth()
  router.push('/login')
}

const handleAddOutputParam = () => {
  outputParams.value = [...outputParams.value, { name: '', type: 'input', value: '' }]
}

const handleRemoveOutputParam = (index: number) => {
  outputParams.value = outputParams.value.filter((_, i) => i !== index)
}

const handleUpdateOutputParam = (index: number, field: keyof OutputParam, value: string) => {
  const newParams = [...outputParams.value]
  newParams[index] = { ...newParams[index], [field]: value }
  outputParams.value = newParams
}

const getReferenceableNodes = () => {
  if (!selectedNode.value) return []

  const sourceIds = Array.from(
    new Set(
      edges.value
        .filter((edge) => edge.target === selectedNode.value?.id)
        .map((edge) => edge.source)
    )
  )

  return sourceIds
    .map((sourceId) => nodes.value.find((node) => node.id === sourceId))
    .filter((node): node is Node => Boolean(node))
}

const getNodeOutputParams = (nodeType: string): string[] => {
  switch (nodeType) {
    case 'input':
      return ['user_input']
    case 'llm':
    case 'react_agent':
    case 'openai':
    case 'deepseek':
    case 'qwen':
    case 'step':
    case 'zhipu':
    case 'ai_ping':
      return nodeType === 'react_agent'
        ? ['output', 'finalAnswer', 'steps', 'tokens']
        : ['output', 'tokens']
    case 'tts':
      return ['audioUrl', 'fileName', 'output']
    case 'web_search':
      return ['summary', 'results', 'citations', 'output']
    case 'web_fetch':
      return ['content', 'pages', 'citations', 'output']
    case 'memory_write':
      return ['memoryId', 'scope', 'stored']
    case 'memory_retrieve':
      return ['context', 'memories', 'citations', 'output']
    case 'knowledge_upsert':
      return ['knowledgeBaseId', 'contentId', 'chunkCount', 'indexed', 'output']
    case 'knowledge_retrieve':
      return ['context', 'chunks', 'citations', 'output']
    case 'image_generate':
      return ['imageUrl', 'imageUrls', 'prompt', 'output']
    case 'video_generate':
      return ['videoUrl', 'coverUrl', 'taskId', 'status', 'output']
    default:
      return ['output']
  }
}

const getConfiguredOutputParamNames = (node: Node) => {
  const nodeType = (node.data?.type as string) || ''
  if (nodeType === 'input') {
    return ['user_input']
  }

  if (!Array.isArray(node.data?.outputParams)) {
    if (nodeType === 'image_generate' || nodeType === 'video_generate') {
      return getNodeOutputParams(nodeType)
    }
    return []
  }

  return (node.data.outputParams as Array<{ name?: string }>)
    .map((param) => param.name?.trim())
    .filter((name): name is string => Boolean(name))
}

const getReferenceableParams = () => {
  const params: { label: string; value: string }[] = []
  getReferenceableNodes().forEach((node) => {
    const nodeLabel = (node.data?.label as string) || node.id
    const outputParamsOfNode = Array.from(new Set(getConfiguredOutputParamNames(node)))

    outputParamsOfNode.forEach((param) => {
      params.push({
        label: `${nodeLabel}.${param}`,
        value: `${node.id}.${param}`,
      })
    })
  })
  return params
}

const handleSaveOutputConfig = () => {
  if (!selectedNode.value) return

  for (const param of outputParams.value) {
    if (!param.name) {
      message.warning('请填写所有参数名')
      return
    }
    if (param.type === 'input' && !param.value) {
      message.warning('请填写输入值')
      return
    }
    if (param.type === 'reference' && !param.referenceNode) {
      message.warning('请选择引用参数')
      return
    }
  }

  const paramNames = new Set(outputParams.value.map((p) => p.name))
  const templateParamRegex = /\{\{(\w+)\}\}/g
  const matches = responseContent.value.matchAll(templateParamRegex)
  const undefinedParams: string[] = []

  for (const match of matches) {
    const paramName = match[1]
    if (!paramNames.has(paramName)) {
      undefinedParams.push(paramName)
    }
  }

  if (undefinedParams.length > 0) {
    message.warning(`回答内容中引用了未定义的参数: ${undefinedParams.join(', ')}`)
    return
  }

  const updatedData = {
    ...selectedNode.value.data,
    outputParams: outputParams.value,
    responseContent: responseContent.value,
  }

  workflowStore.updateNode(selectedNode.value.id, updatedData)
  message.success('配置保存成功')
}

const handleOpenLoadModal = async () => {
  loadingWorkflows.value = true
  loadModalOpen.value = true
  try {
    const result = await getWorkflows()
    if (result.code === 200) {
      workflows.value = result.data
    }
  } catch {
    message.error('获取工作流列表失败')
  } finally {
    loadingWorkflows.value = false
  }
}

const handleLoadWorkflow = (workflow: Workflow) => {
  loadModalOpen.value = false
  router.push(`/editor/${workflow.id}`)
}

const handleDeleteWorkflow = async (workflow: Workflow) => {
  deletingWorkflowId.value = workflow.id
  try {
    const result = await deleteWorkflow(workflow.id)
    if (result.code !== 200) {
      message.error(result.message || '删除工作流失败')
      return
    }

    workflows.value = workflows.value.filter((item) => item.id !== workflow.id)
    message.success('工作流已删除')

    if (activeWorkflowId.value === workflow.id) {
      hasLoadedRef.value = null
      setCurrentWorkflowId(null)
      workflowName.value = '未命名工作流'
      engineType.value = 'dag'
      outputParams.value = []
      responseContent.value = ''
      setNodes(createDefaultWorkflowNodes())
      setEdges([])
      router.replace('/editor')
    }
  } catch {
    message.error('删除工作流失败')
  } finally {
    deletingWorkflowId.value = null
  }
}

const handleCreateNew = () => {
  setCurrentWorkflowId(null)
  workflowName.value = '未命名工作流'

  setNodes(createDefaultWorkflowNodes())
  setEdges([])
  router.push('/editor')
  message.info('已创建新工作流')
}

const handleSaveLlmConfig = () => {
  if (!selectedNode.value) return

  for (const param of llmInputParams.value) {
    if (!param.name) {
      message.warning('请填写所有参数名')
      return
    }
    if (param.type === 'input' && !param.value) {
      message.warning('请填写输入值')
      return
    }
    if (param.type === 'reference' && !param.referenceNode) {
      message.warning('请选择引用参数')
      return
    }
  }

  if (!llmConfig.prompt) {
    message.warning('请填写提示词模板')
    return
  }

  const paramNames = new Set(llmInputParams.value.map((p) => p.name))
  const templateParamRegex = /\{\{(\w+)\}\}/g
  const matches = llmConfig.prompt.matchAll(templateParamRegex)
  const undefinedParams: string[] = []

  for (const match of matches) {
    const paramName = match[1]
    if (!paramNames.has(paramName)) {
      undefinedParams.push(paramName)
    }
  }

  if (undefinedParams.length > 0) {
    message.warning(`提示词模板中引用了未定义的参数: ${undefinedParams.join(', ')}`)
    return
  }

  if (!llmConfig.configId) {
    if (!llmConfig.provider) {
      message.warning('请选择供应商')
      return
    }
    if (!llmConfig.apiUrl) {
      message.warning('请选择全局配置或填写 API 地址')
      return
    }
    if (!llmConfig.apiKey) {
      message.warning('请选择全局配置或填写 API 密钥')
      return
    }
    if (!llmConfig.model) {
      message.warning('请选择全局配置或填写模型名称')
      return
    }
  }

  const useGlobalConfig = !!llmConfig.configId
  const nextAgentStrategy =
    selectedNode.value.data?.type === 'react_agent' ? 'react' : llmConfig.agentStrategy
  const selectedKnowledgeBaseName = llmConfig.knowledgeBaseId
    ? knowledgeBases.value.find((base) => String(base.id) === llmConfig.knowledgeBaseId)?.name ||
      llmConfig.knowledgeBaseName
    : ''
  const updatedData = {
    ...selectedNode.value.data,
    provider: llmConfig.provider,
    configId: llmConfig.configId,
    apiUrl: useGlobalConfig ? '' : llmConfig.apiUrl,
    apiKey: useGlobalConfig ? '' : llmConfig.apiKey,
    model: useGlobalConfig ? '' : llmConfig.model,
    temperature: llmConfig.temperature,
    prompt: llmConfig.prompt,
    skillName: llmConfig.skillName,
    maxSteps: llmConfig.maxSteps,
    agentStrategy: nextAgentStrategy,
    tools:
      nextAgentStrategy === 'react'
        ? buildRuntimeToolSelection(llmConfig.tools, llmConfig.mcpToolIds)
        : [],
    memoryEnabled: llmConfig.memoryEnabled,
    memoryTopK: llmConfig.memoryTopK,
    mcpToolIds: nextAgentStrategy === 'react' ? llmConfig.mcpToolIds : [],
    knowledgeBaseId: llmConfig.knowledgeBaseId,
    knowledgeBaseName: selectedKnowledgeBaseName,
    knowledgeTopK: llmConfig.knowledgeTopK,
    knowledgeScoreThreshold: llmConfig.knowledgeScoreThreshold,
    inputParams: llmInputParams.value,
    outputParams: llmOutputParams.value,
  }

  workflowStore.updateNode(selectedNode.value.id, updatedData)
  message.success('配置保存成功')
}

const handleAddLlmInputParam = () => {
  llmInputParams.value = [...llmInputParams.value, { name: '', type: 'input', value: '' }]
}

const handleRemoveLlmInputParam = (index: number) => {
  llmInputParams.value = llmInputParams.value.filter((_, i) => i !== index)
}

const handleUpdateLlmInputParam = (index: number, field: keyof LlmInputParam, value: string) => {
  const newParams = [...llmInputParams.value]
  newParams[index] = { ...newParams[index], [field]: value }
  llmInputParams.value = newParams
}

const handleSaveTtsConfig = () => {
  if (!selectedNode.value) return

  if (!ttsConfig.configId) {
    if (!ttsConfig.provider) {
      message.warning('请选择供应商')
      return
    }
    if (!ttsConfig.apiUrl) {
      message.warning('请选择全局配置或填写 API 地址')
      return
    }
    if (!ttsConfig.apiKey) {
      message.warning('请选择全局配置或填写 API Key')
      return
    }
    if (!ttsConfig.model) {
      message.warning('请选择全局配置或填写模型名称')
      return
    }
  }

  if (normalizeProviderKey(ttsConfig.provider) === 'step' && ttsConfig.instruction.length > 200) {
    message.warning('StepAudio 2.5 TTS 的 instruction 不能超过 200 字符')
    return
  }

  for (const param of ttsInputParams.value) {
    if (!param.name) {
      message.warning('请填写所有参数名')
      return
    }
    if (param.type === 'input' && !param.value) {
      message.warning('请填写输入值')
      return
    }
    if (param.type === 'reference' && !param.referenceNode) {
      message.warning('请选择引用参数')
      return
    }
  }

  for (const param of ttsOutputParams.value) {
    if (!param.name) {
      message.warning('请填写所有输出参数名')
      return
    }
  }

  const useGlobalConfig = !!ttsConfig.configId
  const updatedData = {
    ...selectedNode.value.data,
    provider: ttsConfig.provider,
    configId: ttsConfig.configId,
    apiUrl: useGlobalConfig ? '' : ttsConfig.apiUrl,
    apiKey: useGlobalConfig ? '' : ttsConfig.apiKey,
    model: useGlobalConfig ? '' : ttsConfig.model,
    voice: ttsConfig.voice,
    languageType: ttsConfig.languageType,
    instruction: ttsConfig.instruction,
    speed: ttsConfig.speed,
    volume: ttsConfig.volume,
    sampleRate: ttsConfig.sampleRate,
    inputParams: ttsInputParams.value,
    outputParams: ttsOutputParams.value,
  }

  workflowStore.updateNode(selectedNode.value.id, updatedData)
  message.success('配置保存成功')
}

const handleAddTtsInputParam = () => {
  ttsInputParams.value = [...ttsInputParams.value, { name: '', type: 'input', value: '' }]
}

const handleRemoveTtsInputParam = (index: number) => {
  ttsInputParams.value = ttsInputParams.value.filter((_, i) => i !== index)
}

const handleUpdateTtsInputParam = (index: number, field: keyof TtsInputParam, value: string) => {
  const newParams = [...ttsInputParams.value]
  newParams[index] = { ...newParams[index], [field]: value }
  ttsInputParams.value = newParams
}

const handleAddTtsOutputParam = () => {
  ttsOutputParams.value = [...ttsOutputParams.value, { name: '', value: '' }]
}

const handleRemoveTtsOutputParam = (index: number) => {
  ttsOutputParams.value = ttsOutputParams.value.filter((_, i) => i !== index)
}

const handleUpdateTtsOutputParam = (index: number, field: keyof TtsOutputParam, value: string) => {
  const newParams = [...ttsOutputParams.value]
  newParams[index] = { ...newParams[index], [field]: value }
  ttsOutputParams.value = newParams
}

const handleAddLlmOutputParam = () => {
  llmOutputParams.value = [...llmOutputParams.value, { name: '', type: 'string', description: '' }]
}

const handleRemoveLlmOutputParam = (index: number) => {
  llmOutputParams.value = llmOutputParams.value.filter((_, i) => i !== index)
}

const handleUpdateLlmOutputParam = (index: number, field: keyof LlmOutputParam, value: string) => {
  const newParams = [...llmOutputParams.value]
  newParams[index] = { ...newParams[index], [field]: value }
  llmOutputParams.value = newParams
}

const applyLlmConfigToSelectedNode = () => {
  const node = selectedNode.value
  if (!node) return

  const useGlobalConfig = !!llmConfig.configId
  const nextAgentStrategy = node.data?.type === 'react_agent' ? 'react' : llmConfig.agentStrategy
  const selectedKnowledgeBaseName = llmConfig.knowledgeBaseId
    ? knowledgeBases.value.find((base) => String(base.id) === llmConfig.knowledgeBaseId)?.name ||
      llmConfig.knowledgeBaseName
    : ''

  workflowStore.updateNode(node.id, {
    ...node.data,
    provider: llmConfig.provider,
    configId: llmConfig.configId,
    apiUrl: useGlobalConfig ? '' : llmConfig.apiUrl,
    apiKey: useGlobalConfig ? '' : llmConfig.apiKey,
    model: useGlobalConfig ? '' : llmConfig.model,
    temperature: llmConfig.temperature,
    prompt: llmConfig.prompt,
    skillName: llmConfig.skillName,
    maxSteps: llmConfig.maxSteps,
    agentStrategy: nextAgentStrategy,
    tools:
      nextAgentStrategy === 'react'
        ? buildRuntimeToolSelection(llmConfig.tools, llmConfig.mcpToolIds)
        : [],
    memoryEnabled: llmConfig.memoryEnabled,
    memoryTopK: llmConfig.memoryTopK,
    mcpToolIds: nextAgentStrategy === 'react' ? llmConfig.mcpToolIds : [],
    knowledgeBaseId: llmConfig.knowledgeBaseId,
    knowledgeBaseName: selectedKnowledgeBaseName,
    knowledgeTopK: llmConfig.knowledgeTopK,
    knowledgeScoreThreshold: llmConfig.knowledgeScoreThreshold,
    inputParams: llmInputParams.value,
    outputParams: llmOutputParams.value,
  })
}

const selectedNodeType = computed(() => String(selectedNode.value?.data?.type || ''))
const isLegacyReActNode = computed(() => selectedNodeType.value === 'react_agent')
const isGenericLlmNode = computed(() => selectedNodeType.value === 'llm')
const isReActMode = computed(
  () =>
    (isGenericLlmNode.value && llmConfig.agentStrategy === 'react') || isLegacyReActNode.value
)
const isAgentPlanNode = computed(() =>
  [
    'web_search',
    'web_fetch',
    'memory_write',
    'memory_retrieve',
    'knowledge_upsert',
    'knowledge_retrieve',
    'image_generate',
    'video_generate',
  ].includes(selectedNodeType.value)
)
const selectedNodeProvider = computed(() => resolveSelectedNodeProvider(selectedNode.value))
const agentToolOptions = [{ label: '写入记忆', value: 'memory_write' }]

const availableLlmConfigs = computed(() =>
  isGenericLlmNode.value || isLegacyReActNode.value
    ? llmGlobalConfigs.value
    : llmGlobalConfigs.value.filter(
        (config) => normalizeProviderKey(config.provider) === selectedNodeProvider.value
      )
)

const ttsProviderOptions = computed(() =>
  providerOptions.value.filter((option) => ['qwen', 'step'].includes(option.value))
)
const normalizedTtsProvider = computed(() => normalizeProviderKey(ttsConfig.provider))
const availableTtsConfigs = computed(() =>
  llmGlobalConfigs.value.filter((config) =>
    ['qwen', 'step'].includes(normalizeProviderKey(config.provider))
  )
)
const isStepTtsProvider = computed(() => normalizedTtsProvider.value === 'step')
const hasTtsProvider = computed(() => ['qwen', 'step'].includes(normalizedTtsProvider.value))

const availableAgentPlanConfigs = computed(() =>
  llmGlobalConfigs.value.filter(
    (config) => normalizeProviderKey(config.provider) === 'volcengine_agent_plan'
  )
)
const imageGenerationProviderOptions = computed(() => providerOptions.value)
const availableImageGenerateConfigs = computed(() =>
  llmGlobalConfigs.value.filter((config) => {
    const provider = normalizeProviderKey(config.provider)
    return provider === 'volcengine_agent_plan' || !!config.imageModel
  })
)
const availableVideoGenerateConfigs = computed(() =>
  llmGlobalConfigs.value.filter((config) => {
    const provider = normalizeProviderKey(config.provider)
    return provider === 'volcengine_agent_plan' || !!config.videoModel
  })
)
const availableToolConfigs = computed(() =>
  selectedNodeType.value === 'image_generate'
    ? availableImageGenerateConfigs.value
    : selectedNodeType.value === 'video_generate'
      ? availableVideoGenerateConfigs.value
      : availableAgentPlanConfigs.value
)
const selectedToolProvider = computed(
  () =>
    normalizeProviderKey(String(selectedNode.value?.data?.provider || '')) ||
    'volcengine_agent_plan'
)
const selectedToolConfig = computed(() => {
  const configId = selectedNode.value?.data?.configId
  return configId ? llmGlobalConfigs.value.find((config) => config.id === configId) : undefined
})
const selectedImageModel = computed(() =>
  String(
    selectedNode.value?.data?.model ||
      selectedToolConfig.value?.imageModel ||
      selectedToolConfig.value?.model ||
      ''
  )
)
const isStepImageEditModel = computed(
  () => selectedToolProvider.value === 'step' && selectedImageModel.value === 'step-image-edit-2'
)

const stepImageSizeOptions = computed(() =>
  isStepImageEditModel.value
    ? [
        { value: '768x1360', label: '768x1360 横版' },
        { value: '896x1184', label: '896x1184 横版' },
        { value: '1024x1024', label: '1024x1024 方图' },
        { value: '1184x896', label: '1184x896 竖版' },
        { value: '1360x768', label: '1360x768 竖版' },
      ]
    : [
        { value: '1280x800', label: '1280x800 横版' },
        { value: '1024x1024', label: '1024x1024 方图' },
        { value: '800x1280', label: '800x1280 竖版' },
        { value: '768x768', label: '768x768 方图' },
        { value: '512x512', label: '512x512 方图' },
      ]
)

const imageOutputFieldOptions = computed(() =>
  getNodeOutputParams('image_generate').map((field) => ({ value: field, label: field }))
)
const videoOutputFieldOptions = computed(() =>
  getNodeOutputParams('video_generate').map((field) => ({ value: field, label: field }))
)

const knowledgeBaseOptions = computed(() =>
  knowledgeBases.value.map((base) => ({
    value: String(base.id),
    label: `${base.name}（${base.documentCount || 0} 文档 / ${base.chunkCount || 0} 分片）`,
  }))
)

const mcpToolOptions = computed(() =>
  mcpTools.value
    .filter((tool) => tool.enabled === 1)
    .map((tool) => ({
      value: String(tool.id),
      label: `${tool.name}（${tool.toolName}）`,
    }))
)

const agentPlanConfigLabel = computed(() =>
  selectedNodeType.value === 'image_generate'
    ? '图片生成全局配置'
    : selectedNodeType.value === 'video_generate'
      ? '视频生成全局配置'
      : 'Agent Plan 全局配置'
)

const agentPlanConfigPlaceholder = computed(() =>
  selectedNodeType.value === 'image_generate'
    ? '选择带图片能力的全局配置'
    : selectedNodeType.value === 'video_generate'
      ? '选择带视频能力的全局配置'
      : '选择火山方舟 Agent Plan 配置'
)

const agentPlanApiUrlPlaceholder = computed(() => {
  if (selectedNodeType.value === 'image_generate' && selectedToolProvider.value === 'step') {
    return isStepImageEditModel.value
      ? 'https://api.stepfun.com/step_plan/v1'
      : 'https://api.stepfun.com/v1'
  }
  return 'https://ark.cn-beijing.volces.com/api/plan/v3'
})

const agentPlanModelPlaceholder = computed(() =>
  selectedNodeType.value === 'image_generate' && selectedToolProvider.value === 'step'
    ? '可选，例如 step-image-edit-2 或 step-1x-medium'
    : '可选。为空时使用全局配置里的对应模型'
)

const selectedNodeLabel = computed(
  () => String(selectedNode.value?.data?.label || selectedNode.value?.id || '')
)

const updateSelectedNodeData = (patch: Record<string, unknown>) => {
  const node = selectedNode.value
  if (!node) return
  const updatedData = { ...node.data, ...patch }
  workflowStore.updateNode(node.id, updatedData)
  workflowStore.setSelectedNode({ ...node, data: updatedData })
}

const handleAgentStrategyChange = (value: unknown) => {
  const strategy = String(value)
  Object.assign(llmConfig, {
    agentStrategy: strategy,
    tools: strategy === 'react' ? llmConfig.tools : [],
    mcpToolIds: strategy === 'react' ? llmConfig.mcpToolIds : [],
  })
}

const handleKnowledgeBaseChange = (value: unknown) => {
  const knowledgeBaseId = value ? String(value) : undefined
  const selectedBase = knowledgeBases.value.find((base) => String(base.id) === knowledgeBaseId)
  Object.assign(llmConfig, {
    knowledgeBaseId,
    knowledgeBaseName: selectedBase?.name || '',
  })
}

const handleLlmConfigSelect = (value: unknown) => {
  if (value) {
    const config = llmGlobalConfigs.value.find((c) => c.id === Number(value))
    if (config) {
      Object.assign(llmConfig, {
        provider: normalizeProviderKey(config.provider),
        configId: Number(value),
        apiUrl: config.apiUrl,
        apiKey: '',
        model: config.model,
      })
    }
  } else {
    Object.assign(llmConfig, {
      provider: isGenericLlmNode.value ? '' : selectedNodeProvider.value,
      configId: undefined,
      apiUrl: '',
      apiKey: '',
      model: '',
    })
  }
}

const handleTtsConfigSelect = (value: unknown) => {
  if (value) {
    const config = llmGlobalConfigs.value.find((c) => c.id === Number(value))
    if (config) {
      const provider = normalizeProviderKey(config.provider)
      const providerChanged = provider !== normalizedTtsProvider.value
      Object.assign(ttsConfig, {
        provider,
        configId: Number(value),
        apiUrl: config.apiUrl,
        apiKey: '',
        model: getTtsModelForProvider(provider, config.ttsModel, config.model),
        voice: providerChanged ? getDefaultTtsVoice(provider) : ttsConfig.voice,
      })
    }
  } else {
    Object.assign(ttsConfig, {
      configId: undefined,
      apiUrl: '',
      apiKey: '',
      model: getDefaultTtsModel(normalizedTtsProvider.value),
    })
  }
}

const handleTtsProviderChange = (value: unknown) => {
  const provider = String(value)
  Object.assign(ttsConfig, {
    provider,
    model: getDefaultTtsModel(provider),
    voice: getDefaultTtsVoice(provider),
  })
}

const handleToolConfigSelect = (value: unknown) => {
  if (value) {
    const config = llmGlobalConfigs.value.find((c) => c.id === Number(value))
    const provider = config ? normalizeProviderKey(config.provider) : 'volcengine_agent_plan'
    const imageModel = config?.imageModel || config?.model || ''
    const nextData: Record<string, unknown> = {
      provider,
      configId: Number(value),
      apiUrl: config?.apiUrl || '',
      apiKey: '',
      model: '',
    }
    if (selectedNodeType.value === 'image_generate') {
      nextData.size =
        provider === 'step'
          ? getDefaultStepImageSize(imageModel)
          : (selectedNode.value?.data?.size as string) || '2K'
      nextData.steps =
        provider === 'step' && imageModel === 'step-image-edit-2'
          ? 8
          : selectedNode.value?.data?.steps
      nextData.cfgScale =
        provider === 'step' && imageModel === 'step-image-edit-2'
          ? 1
          : selectedNode.value?.data?.cfgScale
      nextData.textMode =
        provider === 'step' && imageModel === 'step-image-edit-2'
          ? true
          : selectedNode.value?.data?.textMode
    }
    updateSelectedNodeData(nextData)
  } else {
    updateSelectedNodeData({
      provider:
        selectedNodeType.value === 'image_generate'
          ? selectedToolProvider.value
          : 'volcengine_agent_plan',
      configId: undefined,
      apiUrl: '',
      apiKey: '',
      model: '',
    })
  }
}

const handleImageProviderChange = (value: unknown) => {
  const provider = String(value)
  updateSelectedNodeData({
    provider,
    apiUrl: provider === 'step' ? 'https://api.stepfun.com/v1' : '',
    model: '',
    size: provider === 'step' ? '1280x800' : '2K',
  })
}

const handleAgentPlanApiUrlInput = (event: Event) => {
  updateSelectedNodeData({
    provider:
      selectedNodeType.value === 'image_generate'
        ? selectedToolProvider.value
        : 'volcengine_agent_plan',
    apiUrl: inputValue(event),
  })
}

const handleAgentPlanModelInput = (event: Event) => {
  const model = inputValue(event).trim()
  updateSelectedNodeData({
    model,
    size:
      selectedToolProvider.value === 'step' && model
        ? getDefaultStepImageSize(model)
        : selectedNode.value?.data?.size,
    steps:
      selectedToolProvider.value === 'step' && model === 'step-image-edit-2'
        ? 8
        : selectedNode.value?.data?.steps,
    cfgScale:
      selectedToolProvider.value === 'step' && model === 'step-image-edit-2'
        ? 1
        : selectedNode.value?.data?.cfgScale,
    textMode:
      selectedToolProvider.value === 'step' && model === 'step-image-edit-2'
        ? true
        : selectedNode.value?.data?.textMode,
  })
}

const handleReferenceImageUpload = async (file: File) => {
  if (!file.type.startsWith('image/')) {
    message.warning('请选择图片文件')
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    message.warning('图片大小不能超过 10MB')
    return
  }

  try {
    const result = await uploadWorkflowImage(file)
    if (result.code === 200 && result.data?.url) {
      updateSelectedNodeData({ referenceImageUrl: result.data.url })
      message.success('原图上传成功')
    } else {
      message.error(result.message || '原图上传失败')
    }
  } catch (error: any) {
    message.error(error?.message || '原图上传失败')
  }
}

const beforeUploadImage = (file: File) => {
  void handleReferenceImageUpload(file)
  return false
}

const getAgentPlanInputParams = () =>
  Array.isArray(selectedNode.value?.data?.inputParams)
    ? (selectedNode.value?.data?.inputParams as TtsInputParam[])
    : []

const getAgentPlanOutputParams = () =>
  Array.isArray(selectedNode.value?.data?.outputParams)
    ? (selectedNode.value?.data?.outputParams as TtsOutputParam[])
    : []

const addAgentPlanInputParam = (name = '') => {
  updateSelectedNodeData({
    inputParams: [...getAgentPlanInputParams(), { name, type: 'reference', value: '' }],
  })
}

const updateAgentPlanInputParam = (index: number, field: keyof TtsInputParam, value: string) => {
  const nextParams = [...getAgentPlanInputParams()]
  nextParams[index] = { ...nextParams[index], [field]: value }
  updateSelectedNodeData({ inputParams: nextParams })
}

const removeAgentPlanInputParam = (index: number) => {
  updateSelectedNodeData({
    inputParams: getAgentPlanInputParams().filter((_, i) => i !== index),
  })
}

const addAgentPlanOutputParam = (name = '', value = '') => {
  updateSelectedNodeData({
    outputParams: [...getAgentPlanOutputParams(), { name, value }],
  })
}

const updateAgentPlanOutputParam = (index: number, field: keyof TtsOutputParam, value: string) => {
  const nextParams = [...getAgentPlanOutputParams()]
  nextParams[index] = { ...nextParams[index], [field]: value }
  updateSelectedNodeData({ outputParams: nextParams })
}

const removeAgentPlanOutputParam = (index: number) => {
  updateSelectedNodeData({
    outputParams: getAgentPlanOutputParams().filter((_, i) => i !== index),
  })
}

watch(
  [llmGlobalConfigs, selectedNode, llmConfig],
  () => {
    if (!selectedNode.value) return
    if (!isLlmNodeType(String(selectedNode.value.data?.type || ''))) return
    if (!llmConfig.configId) return

    const config = llmGlobalConfigs.value.find((c) => c.id === llmConfig.configId)
    if (!config) return

    const needsSync =
      llmConfig.apiUrl !== config.apiUrl ||
      llmConfig.model !== config.model ||
      llmConfig.apiKey !== ''

    if (needsSync) {
      Object.assign(llmConfig, {
        provider: normalizeProviderKey(config.provider),
        apiUrl: config.apiUrl,
        apiKey: '',
        model: config.model,
      })
    }
  },
  { deep: true }
)

watch(
  [llmGlobalConfigs, selectedNode, ttsConfig],
  () => {
    if (!selectedNode.value || selectedNode.value.data?.type !== 'tts') return
    if (!ttsConfig.configId) return

    const config = llmGlobalConfigs.value.find((c) => c.id === ttsConfig.configId)
    if (!config) return
    const provider = normalizeProviderKey(config.provider)
    const model = getTtsModelForProvider(provider, config.ttsModel, config.model)

    const needsSync =
      ttsConfig.apiUrl !== config.apiUrl ||
      ttsConfig.model !== model ||
      ttsConfig.apiKey !== ''

    if (needsSync) {
      Object.assign(ttsConfig, {
        provider,
        apiUrl: config.apiUrl,
        apiKey: '',
        model,
      })
    }
  },
  { deep: true }
)

watch(
  [knowledgeBases, nodes],
  () => {
    const enrichedNodes = enrichKnowledgeBaseNames(nodes.value, knowledgeBases.value)
    if (enrichedNodes !== nodes.value) {
      setNodes(enrichedNodes)
    }
  }
)

watch(
  () => route.params.id,
  (value) => {
    if (!value) return
    const raw = Array.isArray(value) ? value[0] : value
    const workflowId = Number.parseInt(raw, 10)
    if (Number.isNaN(workflowId)) return
    if (hasLoadedRef.value !== workflowId) {
      hasLoadedRef.value = workflowId
      loadWorkflowById(workflowId)
    }
  },
  { immediate: true }
)

watch(
  [outputParams, responseContent, selectedNode],
  () => {
    if (autoSaveTimerRef.value) {
      clearTimeout(autoSaveTimerRef.value)
      autoSaveTimerRef.value = null
    }

    const node = selectedNode.value
    if (!node || node.data?.type !== 'output') return

    autoSaveTimerRef.value = window.setTimeout(() => {
      let hasValidData = false

      if (outputParams.value.length > 0) {
        hasValidData = outputParams.value.some(
          (param) => param.name && (param.value || param.referenceNode)
        )
      }

      if (responseContent.value && responseContent.value.trim()) {
        hasValidData = true
      }

      if (!hasValidData) return

      workflowStore.updateNode(node.id, {
        ...node.data,
        outputParams: outputParams.value,
        responseContent: responseContent.value,
      })
    }, 500)
  },
  { deep: true }
)

watch(
  [llmConfig, llmInputParams, llmOutputParams, knowledgeBases, selectedNode],
  () => {
    if (autoSaveTimerRef.value) {
      clearTimeout(autoSaveTimerRef.value)
      autoSaveTimerRef.value = null
    }

    const node = selectedNode.value
    if (!node) return
    if (!isLlmNodeType(String(node.data?.type || ''))) return

    autoSaveTimerRef.value = window.setTimeout(() => {
      const hasBasicConfig =
        llmConfig.configId ||
        llmConfig.apiUrl ||
        llmConfig.apiKey ||
        llmConfig.model ||
        llmConfig.prompt
      const hasParams = llmInputParams.value.length > 0 || llmOutputParams.value.length > 0

      if (!hasBasicConfig && !hasParams) return

      applyLlmConfigToSelectedNode()
    }, 500)
  },
  { deep: true }
)

watch(
  [ttsConfig, ttsInputParams, ttsOutputParams, selectedNode],
  () => {
    if (autoSaveTimerRef.value) {
      clearTimeout(autoSaveTimerRef.value)
      autoSaveTimerRef.value = null
    }

    const node = selectedNode.value
    if (!node || node.data?.type !== 'tts') return

    autoSaveTimerRef.value = window.setTimeout(() => {
      const hasBasicConfig =
        ttsConfig.configId || ttsConfig.apiUrl || ttsConfig.apiKey || ttsConfig.model
      const hasParams = ttsInputParams.value.length > 0 || ttsOutputParams.value.length > 0

      if (!hasBasicConfig && !hasParams) return

      const useGlobalConfig = !!ttsConfig.configId
      workflowStore.updateNode(node.id, {
        ...node.data,
        provider: ttsConfig.provider,
        configId: ttsConfig.configId,
        apiUrl: useGlobalConfig ? '' : ttsConfig.apiUrl,
        apiKey: useGlobalConfig ? '' : ttsConfig.apiKey,
        model: useGlobalConfig ? '' : ttsConfig.model,
        voice: ttsConfig.voice,
        languageType: ttsConfig.languageType,
        instruction: ttsConfig.instruction,
        speed: ttsConfig.speed,
        volume: ttsConfig.volume,
        sampleRate: ttsConfig.sampleRate,
        inputParams: ttsInputParams.value,
        outputParams: ttsOutputParams.value,
      })
    }, 500)
  },
  { deep: true }
)

onMounted(() => {
  fetchLLMGlobalConfigs()

  getKnowledgeBases()
    .then((result) => {
      if (result.code === 200) {
        knowledgeBases.value = result.data
      }
    })
    .catch(() => {
      knowledgeBases.value = []
    })

  getMcpTools()
    .then((result) => {
      if (result.code === 200) {
        mcpTools.value = result.data
      }
    })
    .catch(() => {
      mcpTools.value = []
    })
})

onBeforeUnmount(() => {
  if (autoSaveTimerRef.value) {
    clearTimeout(autoSaveTimerRef.value)
    autoSaveTimerRef.value = null
  }
})
</script>
