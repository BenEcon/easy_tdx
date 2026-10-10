// Mount the real child watcher beside the real parent setup so catalog arrival
// exercises emitted defaults as well as the parent's request lifecycle.
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import {parse,compileScript} from '@vue/compiler-sfc'
import * as vue from 'vue'

const file=new URL('../src/components/StrategyPicker.vue',import.meta.url)
const content=compileScript(parse(readFileSync(file,'utf8'),{filename:file.pathname}).descriptor,{id:'picker-parent-qa'}).content
const js=ts.transpileModule(content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
export function connectStrategyPicker(state,store){
  const mod={exports:{}}
  vm.runInNewContext(js,{exports:mod.exports,module:mod,require:path=>path==='vue'?vue:{}},{filename:file.pathname})
  const props={
    get strategies(){return store.strategies},get strategy(){return state.strategy.value},
    get params(){return state.params.value},
    get suspendDefaults(){return state.catalogLoading.value||state.catalogError.value},
  }
  mod.exports.default.setup(props,{expose(){},emit(name,value){if(name==='update:params')state.params.value=value}})
}
