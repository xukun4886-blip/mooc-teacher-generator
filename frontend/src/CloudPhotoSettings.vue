<script setup>
import { ref, watch } from 'vue'
const props=defineProps({project:Object,disabled:Boolean})
const emit=defineEmits(['updated'])
const form=ref({}), error=ref(''), notice=ref(''), checking=ref(false), result=ref(null), dirty=ref(false)
watch(()=>props.project?.id,()=>{form.value={mode:'local',url:'',token_env:'MOOC_CLOUD_TOKEN',batch_size:1,timeout_seconds:1800,allow_uploads:false,allow_paid:false,max_cost:0,...props.project?.photo_execution};dirty.value=false;result.value=null;error.value='';notice.value=''}, {immediate:true})
async function api(path,method,body){const r=await fetch(`/api/projects/${props.project.id}/photo-server${path}`,{method,credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(data.error?.message||data.detail||'服务器操作失败');return data}
async function run(save){checking.value=true;error.value='';notice.value='';try{if(save){const p=await api('','PUT',{revision:props.project.revision,settings:form.value});form.value={...form.value,...p.photo_execution};dirty.value=false;emit('updated',p);notice.value='已保存当前课程的照片处理设置。旧讲稿、任务和成片保留。'}else{result.value=await api('/check','POST',form.value);notice.value=result.value.scope}}catch(e){error.value=e.message}finally{checking.value=false}}
</script>
<template>
 <details v-if="project" class="cloud-photo"><summary>照片数字人处理 · {{project.photo_execution?.mode==='cloud'?'云服务器':'本机'}}{{dirty?' · 尚未保存':''}}</summary>
  <fieldset :disabled="disabled||checking" @input="dirty=true;result=null;notice=''">
   <label>照片处理位置<select v-model="form.mode" aria-label="照片处理位置"><option value="local">本机 SadTalker（原有方案）</option><option value="cloud">指定云服务器 SadTalker</option></select></label>
   <template v-if="form.mode==='cloud'">
    <p>仅发送本课程的教师照片与当前驱动音频。PPT、讲稿、数据库、审核和成片合成留在本机；视频人物仍使用原有路径。</p>
    <div class="cloud-grid"><label>API 地址<input v-model="form.url" placeholder="https://你的服务器" aria-label="云服务器 API 地址" autocomplete="off"></label><label>令牌环境变量名<input v-model="form.token_env" aria-label="云服务器令牌环境变量名" autocomplete="off"></label><label>渲染 batch<select v-model.number="form.batch_size"><option :value="1">1 · 基线</option><option :value="2">2 · 需样片评测</option><option :value="4">4 · 需样片评测</option></select></label><label>单片段时限（秒）<input v-model.number="form.timeout_seconds" type="number" min="30" max="7200"></label></div>
    <label><input v-model="form.allow_uploads" type="checkbox">允许本课程的教师照片和当前驱动音频发送到上述服务器</label>
    <label><input v-model="form.allow_paid" type="checkbox">允许服务器声明的计算费用</label><label>单片段计算费用上限（服务器币种）<input v-model.number="form.max_cost" type="number" min="0" step="0.01"></label>
    <p class="hint">密钥通过本机环境变量设置，不填写密码。费用检查按单片段时限估算，不包含租用实例的空闲费、存储费；已有自用服务器可声明费率0。检查连接不会上传素材或推理。</p>
    <button type="button" @click="run(false)">{{checking?'检查中…':'检查连接与版本'}}</button>
    <p v-if="result" role="status">{{result.ready?'服务器配置就绪':'服务器未就绪'}} · {{result.model?.provider}} · {{result.resident_loaded?'模型已常驻':'模型尚未加载'}} · API声明费率 {{result.price?.hourly_rate}} {{result.price?.currency}}/小时。人物质量与速度需样片验证。</p>
    <p v-for="blocker in result?.blockers||[]" :key="blocker.code" class="warning">{{blocker.message}}</p>
   </template>
   <button type="button" @click="run(true)">{{checking?'处理中…':'保存照片处理设置'}}</button>
  </fieldset>
  <p v-if="error" role="alert" class="warning">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
 </details>
</template>
<style scoped>
.cloud-photo{margin:16px 0}.cloud-photo summary{cursor:pointer;font-weight:600}.cloud-photo fieldset{border:1px solid #d6ded9;border-radius:12px;padding:16px;margin-top:12px;min-width:0}.cloud-photo label{display:block;margin:12px 0}.cloud-photo input:not([type=checkbox]),.cloud-photo select{width:100%;box-sizing:border-box;min-height:40px}.cloud-photo button{margin:8px 12px 0 0}.cloud-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.hint{font-size:13px;color:#57645e;line-height:1.7}@media(max-width:640px){.cloud-grid{grid-template-columns:1fr}}
</style>
