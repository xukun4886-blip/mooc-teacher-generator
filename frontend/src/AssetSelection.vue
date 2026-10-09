<script setup>
import {computed} from 'vue'
const props=defineProps({role:String,modelValue:String})
const emit=defineEmits(['update:modelValue'])
const form=computed(()=>{try{return JSON.parse(props.modelValue)}catch{return {}}})
function update(key,value){emit('update:modelValue',JSON.stringify({...form.value,[key]:value}))}
function crop(i,value){const box=[...(form.value.box||[0,0,100,100])];box[i]=value;update('box',box)}
</script>
<template>
<div v-if="role==='photo'" class="form-grid"><label v-for="(label,i) in ['左边界','上边界','右边界','下边界']">{{label}}（像素）<input type="number" :value="form.box?.[i]" @input="crop(i,Number($event.target.value))"></label></div>
<template v-else><div class="form-grid"><label>开始（秒）<input type="number" min="0" step="0.1" :value="form.start" @input="update('start',Number($event.target.value))"></label><label>结束（秒）<input type="number" min="0" step="0.1" :value="form.end" @input="update('end',Number($event.target.value))"></label></div><label v-if="role==='reference_audio'">所选语音片段对应文字<textarea :value="form.transcript" @input="update('transcript',$event.target.value)" rows="3"></textarea></label></template>
</template>
