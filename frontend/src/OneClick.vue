<script setup>
import { ref, computed, onMounted, onUnmounted, defineAsyncComponent, nextTick } from 'vue'
import CloudPhotoSettings from './CloudPhotoSettings.vue'
const Advanced = defineAsyncComponent(() => import('./App.vue'))
const advanced = new URLSearchParams(location.search).has('advanced')
const project=ref(null), projects=ref([]), generation=ref(null), jobs=ref([]), logged=ref(false), token=ref(''), error=ref(''), notice=ref(''), busy=ref(false), connected=ref(true), reviewing=ref(false), watched=ref(false)
const resultPanel=ref(null)
const pid=computed(()=>project.value?.id), person=computed(()=>project.value?.assets[project.value?.config.mode||'photo'])
const roles=['person','pptx','reference_audio'], labels={person:'教师图片或视频',pptx:'课程 PPT',reference_audio:'参考语音'}, accepts={person:'.jpg,.jpeg,.png,.mp4',pptx:'.ppt,.pptx',reference_audio:'.wav,.mp3,.m4a'}, hints={person:'图片或视频，选择其中一种',pptx:'保留原课件画面，自动生成讲解',reference_audio:'用于教师音色，无需录制完整课时'}
const active=computed(()=>generation.value&&['queued','running'].includes(generation.value.state)), processing=computed(()=>jobs.value.some(j=>['queued','running'].includes(j.state)))
const ready=computed(()=>person.value?.state==='ready'&&['pptx','reference_audio'].every(r=>project.value?.assets[r]?.state==='ready'))
const media=computed(()=>generation.value?.media), completed=computed(()=>generation.value?.state==='completed'&&media.value?.result)
const phaseNames={queued:'等待制作',starting:'开始处理',recovering:'恢复制作',recognizing_reference:'识别参考语音，准备教师音色',generating_ai_draft:'根据课件生成中文讲稿',retrying_ai_format:'讲稿格式未通过检查，正在有限重试',waiting_ai_rate_limit:'讲稿服务繁忙，等待后自动重试',preparing_narration:'整理中文讲稿',preparing_video:'准备视频制作',video_queued:'等待视频制作',tts_native_generation:'生成教师语音',photo_native_generation:'生成照片数字人',video_native_generation:'根据原视频生成数字人',composing_original_page:'合成原课件、人物与字幕',validating_and_exporting_course:'检查完整视频并准备下载',recovering_validated_stages:'恢复视频制作',draft_preview_ready:'视频已完成',parsing_structure:'解析 PPT',rendering_original_pages:'准备 PPT 原页',validating_format_and_decode:'检查上传文件',converting_legacy_ppt:'转换 PPT',completed:'已就绪',failed:'处理失败',interrupted:'处理已中断',processing_explicit_selection:'处理选取片段'}
Object.assign(phaseNames,{understanding_slide:'理解原课件图表与公式',generating_narration:'生成中文讲稿正文',deriving_reading:'整理术语读法与逐句对应',generating_teaching_checks:'整理教学核查'})
const phase=computed(()=>phaseNames[generation.value?.stage]||'正在制作')
const failureReason=computed(()=>{const e=generation.value?.error||{};return {AI_RATE_LIMITED:e.message||'讲稿服务当前繁忙，请稍后重试。已生成讲稿会保留。',AI_FORMAT_INVALID:e.message||'讲稿生成结果不完整，请重试生成。',PROCESS_OWNERSHIP_FAILED:'本机媒体进程管理失败，请直接重试。已完成页面会保留。',TIMEOUT:'本次制作超时，请重试。已完成页面会保留。',RESOURCE_INSUFFICIENT:'本机显存或内存不足，请关闭占用资源的程序后重试。'}[e.code]||(/[\u4e00-\u9fff]/.test(e.message||'')?e.message:'视频制作失败，请重试或在高级管理中检查素材与模型。')})
const fileUrl=path=>`/api/projects/${pid.value}/files/${path.split('/').map(encodeURIComponent).join('/')}`
const videoUrl=computed(()=>completed.value?fileUrl(media.value.result.path):'')
const downloadUrl=computed(()=>`/api/projects/${pid.value}/media-jobs/${media.value?.id}/exports/mp4`)
const asset=role=>role==='person'?person.value:project.value?.assets[role]
const assetStage=role=>{const j=jobs.value.find(j=>j.payload.asset_id===asset(role)?.id);return phaseNames[j?.stage]||'检查文件中'}
async function api(path,options={}){const response=await fetch('/api'+path,{credentials:'same-origin',...options,headers:options.body instanceof FormData?{}:{'Content-Type':'application/json'}});const data=await response.json();if(!response.ok)throw new Error(data.error?.message||(typeof data.detail==='string'?data.detail:'操作失败，请重试'));return data}
const post=(path,body={})=>api(path,{method:'POST',body:JSON.stringify(body)})
async function act(fn){busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false}}
async function refresh(){if(!pid.value)return;const id=pid.value;const [p,g,j]=await Promise.all([api(`/projects/${id}`),api(`/projects/${id}/generation`),api(`/projects/${id}/jobs`)]);if(pid.value!==id)return;const finished=g?.state==='completed'&&generation.value?.state!=='completed';if(g?.media?.id!==generation.value?.media?.id)watched.value=false;project.value=p;generation.value=g;jobs.value=j;if(!connected.value&&error.value.startsWith('连接中断'))error.value='';connected.value=true;if(finished){await nextTick();resultPanel.value?.scrollIntoView({behavior:'smooth',block:'start'})}}
async function open(id){await act(async()=>{project.value=await api(`/projects/${id}`);generation.value=null;watched.value=false;sessionStorage.setItem('mooc-simple-project',id);history.replaceState(null,'',`/?project=${id}`);await refresh()})}
function newCourse(){project.value=null;generation.value=null;jobs.value=[];watched.value=false;sessionStorage.removeItem('mooc-simple-project');history.replaceState(null,'','/');notice.value=''}
async function upload(role,event){const file=event.target.files[0];if(!file)return;await act(async()=>{if(!project.value){project.value=await post('/projects',{name:file.name.replace(/\.[^.]+$/,''),config:{layout:'sidebar',size:0.25,target_seconds:45,resolution:'1080p'}});sessionStorage.setItem('mooc-simple-project',pid.value)}const previous=pid.value;const actual=role==='person'?(file.name.toLowerCase().endsWith('.mp4')?'video':'photo'):role;const form=new FormData();form.set('file',file);form.set('revision',project.value.revision);const result=await api(`/projects/${previous}/quick-assets/${actual}`,{method:'POST',body:form});if(result.project_id!==previous){project.value=await api(`/projects/${result.project_id}`);generation.value=null;jobs.value=[];reviewing.value=false;watched.value=false;sessionStorage.setItem('mooc-simple-project',pid.value);history.replaceState(null,'',`/?project=${pid.value}`);notice.value='已切换到新课件，教师形象和参考语音已沿用。原课程、讲稿和成片已保留。'}await refresh()});event.target.value=''}
async function generate(){await act(async()=>{generation.value=await post(`/projects/${pid.value}/generate`);await refresh();await nextTick();resultPanel.value?.scrollIntoView({behavior:'smooth',block:'start'})})}
async function retry(){await act(async()=>{await post(`/projects/${pid.value}/generation/${generation.value.id}/retry`);await refresh()})}
async function retryAsset(role){await act(async()=>{const j=jobs.value.find(j=>j.payload.asset_id===asset(role)?.id);await post(`/projects/${pid.value}/asset-jobs/${j.id}/retry`);await refresh()})}
async function confirm(){await act(async()=>{await post(`/projects/${pid.value}/generation/${generation.value.id}/confirm`,{confirmed:true});reviewing.value=false;await refresh()})}
async function initialize(){projects.value=await api('/projects');logged.value=true;const saved=new URLSearchParams(location.search).get('project')||sessionStorage.getItem('mooc-simple-project');if(saved&&projects.value.some(p=>p.id===saved))await open(saved)}
async function login(){await act(async()=>{await post('/session',{token:token.value});token.value='';await initialize()})}
let timer,polling=false
onMounted(async()=>{if(advanced)return;await act(async()=>{const launch=new URLSearchParams(location.hash.slice(1)).get('launch');if(launch){history.replaceState(null,'',location.pathname+location.search);await post('/session/launch',{ticket:launch})}await initialize()});timer=setInterval(async()=>{if(!logged.value||!pid.value||busy.value||polling)return;polling=true;try{await refresh()}catch(e){connected.value=false;error.value='连接中断，正在重新连接。制作记录会保留。'}finally{polling=false}},2000)})
onUnmounted(()=>clearInterval(timer))
</script>
<template>
 <Advanced v-if="advanced"/>
 <main v-else class="simple-app">
  <header class="simple-header"><a href="/" class="simple-brand">慕课<span>制作</span></a><span>数字人教师</span></header>
  <template v-if="logged">
   <section class="simple-intro"><div class="eyebrow">从课件到课堂</div><h1>让你的课程，开始讲述。</h1><p>上传三项素材，自动制作带讲解、数字人和字幕的慕课视频。</p></section>
   <div v-if="error" class="alert error" role="alert">{{error}}<button v-if="!connected" @click="act(refresh)">重新连接</button><button v-else @click="error=''">关闭</button></div><div v-if="notice" class="alert" role="status">{{notice}}</div>
   <div class="simple-inputs"><section v-for="(role,i) in roles" :key="role" class="upload-card">
    <div class="upload-title"><span>{{i+1}}</span><h2>{{labels[role]}}</h2></div><p>{{hints[role]}}</p>
    <label class="upload-button" :class="{disabled:busy||active||processing}">{{asset(role)?'重新选择':'选择文件'}}<input type="file" :aria-label="labels[role]" :accept="accepts[role]" :disabled="busy||active||processing" @change="upload(role,$event)"></label>
    <template v-if="asset(role)"><p class="file-name">{{asset(role).filename}}</p>
     <img v-if="role==='person'&&project.config.mode==='photo'" :src="fileUrl(asset(role).original)" class="quick-preview" alt="已上传教师图片">
     <video v-if="role==='person'&&project.config.mode==='video'" :src="fileUrl(asset(role).original)" class="quick-preview" controls preload="metadata" aria-label="教师原视频预览"></video>
     <audio v-if="role==='reference_audio'" :src="fileUrl(asset(role).original)" controls preload="metadata" aria-label="参考语音预览"></audio>
     <template v-if="role==='pptx'&&project.slides.length"><p class="page-count">{{project.slides.length}} 页</p><img :src="fileUrl(project.slides[0].image)" class="quick-preview" alt="PPT 原页预览"></template>
     <p v-if="asset(role).state==='ready'" class="ready-text">已就绪</p><p v-else-if="asset(role).state==='failed'" class="warning" role="alert">{{asset(role).error?.message}}<button @click="retryAsset(role)" :disabled="busy||processing">重试处理</button></p><p v-else role="status">{{assetStage(role)}}…</p>
    </template>
   </section></div>
   <div class="generate-area"><button class="primary generate-button" :disabled="!ready||busy||active||processing||!connected" @click="generate">{{active?'正在生成慕课视频':'生成慕课视频'}}</button><p>生成未审核草稿，完成后可播放、下载，再由教师确认。</p></div>
   <section v-if="generation" ref="resultPanel" class="panel generation-panel" aria-live="polite">
    <p v-if="generation.teaching_pending" class="warning">{{generation.teaching_pending}} 页教学核查待完成，讲稿正文已保存。可在高级编辑中仅重试核查；当前成果仍为未审核草稿。</p>
    <p v-if="generation.page_failures?.length" class="warning">未完成页面：{{generation.page_failures.map(f=>project.scenes.find(s=>s.id===f.scene_id)?.source_page_ids.map(id=>project.slides.find(p=>p.source_page_id===id)?.source_index).join('、')).join('、')}}。其他页面已保存。</p>
    <template v-if="active"><span class="badge">未审核草稿</span><h2>{{phase}}</h2><p>讲稿已准备 {{generation.scripts_ready||0}} / {{generation.total}} 页</p><div v-if="media" class="real-progress"><p>语音 {{media.progress.tts}} / {{media.progress.total}} 页</p><p>数字人 {{media.progress.portrait}} / {{media.progress.total}} 页</p><p>画面合成 {{media.progress.compose}} / {{media.progress.total}} 页</p></div><p>可以离开或刷新页面，稍后回来继续查看。</p></template>
     <template v-else-if="generation.state==='failed'"><h2>制作未完成</h2><p class="warning">{{failureReason}}</p><button class="primary" :disabled="busy||generation.retry_allowed===false" @click="retry">重试生成</button><p class="hint">{{generation.retry_allowed===false?'本次制作的重试次数已用完，已完成页面保留。讲稿服务或生成配置修复后可继续制作。':'重试会保留已完成页面，继续处理缺失内容。每次制作最多重试两次。'}}</p></template>
    <template v-else-if="generation.state==='canceled'"><h2>制作已停止</h2><button @click="generate" :disabled="busy">重新生成</button></template>
    <template v-else-if="completed"><div class="section-title"><h2>你的慕课视频已完成</h2><span class="badge">{{generation.teacher_confirmation?'教师已确认 · 草稿文件保留未审核标识':'未审核'}}</span></div><p v-if="generation.is_current===false" class="warning">素材或讲稿已修改，这是修改前的视频。请重新生成后确认。</p>
     <video :key="videoUrl" :src="videoUrl" controls playsinline preload="metadata" class="course-player" aria-label="慕课视频预览"></video>
     <div class="result-actions"><a class="download-button" :href="downloadUrl" download>下载视频</a><button v-if="!generation.teacher_confirmation" @click="reviewing=!reviewing" :disabled="generation.is_current===false">教师确认</button><a :href="`/?advanced=1&project=${pid}`">需要修订</a></div>
     <div v-if="reviewing&&!generation.teacher_confirmation" class="confirmation-box"><p>请核对教学内容、教师形象与音色、口型、字幕及原课件画面。此操作记录教师成片确认，草稿文件保留未审核水印。</p><label><input type="checkbox" v-model="watched">我已观看完整成片，并确认内容与视听效果</label><button class="primary" :disabled="!watched||busy" @click="confirm">确认这份成片</button><button @click="reviewing=false">稍后确认</button></div>
    </template>
   </section>
   <details class="simple-advanced" @toggle="async e=>{if(e.target.open)projects=await api('/projects')}"><summary>高级设置</summary><div class="panel"><p>需要调整讲稿、逐页布局、人工评审或模型检查时再进入。</p><CloudPhotoSettings :project="project" :disabled="busy||active||processing" @updated="p=>{project=p;refresh()}"/><a :href="pid?`/?advanced=1&project=${pid}`:'/?advanced=1'">打开高级编辑与管理</a><button @click="newCourse" :disabled="busy">制作另一门课程</button><p v-if="project?.assets.pptx">可在课程 PPT 中直接重新选择，原课程与审核记录会保留；新课件沿用教师形象和参考语音。</p><label>继续已有课程<select aria-label="继续已有课程" :value="pid||''" @change="e=>{if(e.target.value)open(e.target.value)}"><option value="">选择课程</option><option v-for="p in projects.filter(p=>p.category!=='development')" :value="p.id">{{p.name}}</option></select></label><details><summary>开发验证项目</summary><button v-for="p in projects.filter(p=>p.category==='development')" @click="open(p.id)">{{p.name}}</button></details></div></details>
   <footer class="simple-footer">上传即确认有权使用素材制作课程。{{project?.photo_execution?.mode==='cloud'&&project?.config.mode==='photo'?'教师照片和当前驱动音频发送到指定云服务器；语音生成在本机处理；':'人物和语音在本机处理；'}}课件图文用于已配置的讲稿服务。素材不用于训练。</footer>
  </template>
  <section v-else class="panel local-login"><h1>打开本地慕课制作</h1><p>请运行项目启动器打开本机登录地址，或使用本地访问令牌。</p><label>访问令牌<input v-model="token" type="password" autocomplete="off" aria-label="访问令牌"></label><button class="primary" @click="login">登录</button><p v-if="error" role="alert">{{error}}</p></section>
 </main>
</template>
