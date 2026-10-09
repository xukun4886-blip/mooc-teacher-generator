<script setup>
defineProps({checks:Object,pages:Array,locked:Boolean})
const emit=defineEmits(['change'])
</script>
<template>
<fieldset :disabled="locked" class="review-form" @input="emit('change')" @change="emit('change')">
  <h3>知识点</h3>
  <div v-for="(_,i) in checks.knowledge_points" :key="i" class="review-row"><input v-model="checks.knowledge_points[i]" :aria-label="'知识点 '+(i+1)"><button @click="checks.knowledge_points.splice(i,1);emit('change')">移除</button></div>
  <button @click="checks.knowledge_points.push('');emit('change')">添加知识点</button>
  <h3>术语、数字与公式读法</h3>
  <p class="hint">试听使用实际读法稿。修改此表后，点击“将核查读法应用到当前页”，再核对实际朗读文本。</p>
  <p class="warning" v-for="t in checks.terms.filter(t=>/[\u4e00-\u9fff]/.test(t.text)&&!/[\u4e00-\u9fff]/.test(t.reading))">“{{t.text}}”的建议读法为拼音或英文，请教师核对并填写可朗读的中文读法。</p>
  <div v-for="(t,i) in checks.terms" :key="i" class="review-card"><label>原文<input v-model="t.text" :aria-label="'原文 '+(i+1)"></label><label>中文读法<input v-model="t.reading" :aria-label="'读法 '+(i+1)"></label><button @click="checks.terms.splice(i,1);emit('change')">移除读法项</button></div>
  <button @click="checks.terms.push({text:'',reading:''});emit('change')">添加读法项</button>
  <h3>理解问题与答案来源</h3>
  <div v-for="(q,i) in checks.questions" :key="i" class="review-card"><label>问题 {{i+1}}<textarea v-model="q.question" :aria-label="'理解问题 '+(i+1)" rows="2"></textarea></label><label>参考答案<textarea v-model="q.answer" :aria-label="'参考答案 '+(i+1)" rows="3"></textarea></label><label>答案来源<select v-model="q.source_page_id" :aria-label="'答案来源 '+(i+1)"><option v-for="p in pages" :value="p.source_page_id">原页 {{p.source_index}}</option></select></label><button @click="checks.questions.splice(i,1);emit('change')">移除问题</button></div>
  <button @click="checks.questions.push({question:'',answer:'',source_page_id:pages[0]?.source_page_id||''});emit('change')">添加理解问题</button>
  <h3>待教师判断 · {{checks.pending.length}} 项</h3>
  <p class="hint">请核对原页并修订讲稿或读法，再逐项标记已处理。系统不会自动清零。</p>
  <div v-for="(_,i) in checks.pending" :key="i" class="review-card"><textarea v-model="checks.pending[i]" :aria-label="'待审核项 '+(i+1)" rows="2"></textarea><button @click="checks.pending.splice(i,1);emit('change')">我已核对并处理此项</button></div>
  <button @click="checks.pending.push('');emit('change')">添加待审核项</button>
</fieldset>
</template>
