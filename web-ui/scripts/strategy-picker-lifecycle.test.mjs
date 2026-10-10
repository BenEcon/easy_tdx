import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import {parse,compileScript} from '@vue/compiler-sfc'
import * as vue from 'vue'

const file=new URL('../src/components/StrategyPicker.vue',import.meta.url)
const content=compileScript(parse(readFileSync(file,'utf8'),{filename:file.pathname}).descriptor,{id:'picker-qa'}).content
const js=ts.transpileModule(content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
const schema=(name='ma_cross')=>({name,label:name,params:[{name:'fast',default:5},{name:'slow',default:20}]})
function mount(input){
  const props=vue.reactive(input),mod={exports:{}},events=[]
  vm.runInNewContext(js,{exports:mod.exports,module:mod,require:path=>path==='vue'?vue:{}},{filename:file.pathname})
  const scope=vue.effectScope()
  scope.run(()=>mod.exports.default.setup(props,{expose(){},emit(name,value){events.push([name,value]);if(name==='update:params')props.params=value}}))
  return{props,events,close:()=>scope.stop()}
}
test('initial schema and refreshed catalog preserve supplied parameters; strategy change alone resets',async()=>{
  const h=mount({strategies:[schema()],strategy:'ma_cross',params:{fast:7,slow:31}})
  try{
    assert.equal(h.events.length,0)
    h.props.strategies=[schema(),schema('other')];await vue.nextTick()
    assert.equal(h.events.length,0);assert.equal(h.props.params.fast,7)
    h.props.strategy='other';await vue.nextTick()
    assert.equal(h.props.params.fast,5);assert.equal(h.props.params.slow,20)
  }finally{h.close()}
})
test('late catalog defaults are suspended until route validation and then fill only missing fields',async()=>{
  const h=mount({strategies:[],strategy:'ma_cross',params:{},suspendDefaults:true})
  try{
    h.props.strategies=[schema()];await vue.nextTick();assert.equal(h.events.length,0)
    h.props.params={fast:9}
    h.props.suspendDefaults=false;await vue.nextTick()
    assert.equal(h.props.params.fast,9);assert.equal(h.props.params.slow,20)
    h.props.strategies=[schema()];await vue.nextTick();assert.equal(h.events.length,1)
  }finally{h.close()}
})
