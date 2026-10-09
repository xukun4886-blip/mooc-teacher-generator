<script setup>
import {ref,onMounted} from 'vue'
const props=defineProps({project:Object,api:Function})
const state=ref(null),checks=ref({}),note=ref(''),error=ref(''),notice=ref(''),busy=ref(false)
async function load(){try{state.value=await props.api(`/projects/${props.project.id}/m1-review`);checks.value=Object.fromEntries(Object.keys(state.value.criteria).map(k=>[k,state.value.saved?.checks[k]??null]));note.value=state.value.saved?.note||''}catch(e){error.value=e.message}}
async function save(completed){busy.value=true;error.value='';try{state.value=await props.api(`/projects/${props.project.id}/m1-review`,{method:'POST',body:JSON.stringify({binding:state.value.binding,checks:checks.value,note:note.value,completed})});notice.value=completed?'人工评审已保存；阶段退出仍需按项目标准核查。':'评审草稿已保存，未完成项保留。'}catch(e){error.value=e.message}finally{busy.value=false}}
onMounted(load)
</script>
<template>
<section class="panel"><h2>M1 人物、音色与口型人工评审</h2><p>请播放原素材及真实 A/B 样片，核对人物、声音、口型和连续播放接缝。这里的结论由教师填写。</p>
<p class="warning" v-if="state?.stale">素材或模型已改变，上次评审已过期。</p><p class="warning">照片原图仅 180×168 时请重点核查清晰度；插值放大不会增加真实细节。</p>
<p class="warning" v-if="error">{{error}}</p><p role="status">{{notice}}</p>
<template v-if="state"><p class="hint">{{state.baseline_note}}</p><div class="asset-grid"><article v-for="a in state.gallery" :key="a.id" class="panel"><h3>{{a.label}}</h3>
<img v-if="a.kind==='photo'" class="asset-preview" :src="`/api/projects/${project.id}/m1-review/media/${a.id}`" :alt="a.label">
<audio v-else-if="a.kind==='audio'" controls preload="metadata" :src="`/api/projects/${project.id}/m1-review/media/${a.id}`"></audio>
<video v-else controls preload="metadata" class="asset-preview" :src="`/api/projects/${project.id}/m1-review/media/${a.id}`"></video>
<p class="hint" v-if="a.baseline_sample">M1 已有真实模型输出 · 当前素材原件和选择在上方对照</p><p class="warning" v-if="a.baseline_sample&&!a.compatible_with_current">该样片与当前素材选择或模型配置不兼容，须真实复测，不能计当前正式评审。</p><details><summary>媒体摘要</summary><code>{{a.sha256}}</code></details></article></div>
<p class="hint">原视频播放使用 H.264 浏览器兼容副本，原件和模型驱动视频序列保留。首次人物样片使用完整语音前 30 秒；预热对照 B 使用第 10–40 秒，各自音频不同。</p><details><summary>完整语音讲稿与当前参考片段文字</summary><h3>完整合成语音讲稿</h3><pre>{{state.sample_script||'请对照受控 M1 原始讲稿记录'}}</pre><h3>当前参考片段对应文字</h3><pre>{{state.reference_transcript}}</pre></details>
<div class="form-grid"><label v-for="(label,k) in state.criteria" :key="k">{{label}}<select v-model="checks[k]" :aria-label="label"><option :value="null">待评审</option><option :value="true">人工核查通过</option><option :value="false">需要修复或复测</option></select></label></div>
<label>人工评审记录<textarea v-model="note" rows="4" placeholder="具体观察、问题位置与复测要求" aria-label="M1 人工评审记录"></textarea></label>
<div class="actions"><button @click="save(false)" :disabled="busy||!note.trim()">保存评审草稿</button><button class="primary" @click="save(true)" :disabled="busy||!note.trim()||Object.values(checks).some(v=>v!==true)">我已逐项评审，保存完成结论</button></div><p v-if="state.saved">已保存：{{state.saved.completed?'人工评审完整':'人工评审未完成'}} · {{state.saved.at}}</p>
</template></section>
</template>
