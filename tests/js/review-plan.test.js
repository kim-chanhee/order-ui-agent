import test from 'node:test';
import assert from 'node:assert/strict';
import { cardKeyForBlock } from '../../app/static/js/a2ui/plan/plan-renderer.js';
import { validatePlanForConfirmation } from '../../app/static/js/a2ui/plan/plan-validation.js?v=dynamic-blueprint-v1';
import { installPlanSurface } from '../../app/static/js/a2ui/surfaces.js';
import { reviewState } from '../../app/static/js/a2ui/state.js?v=dynamic-blueprint-v1';
import { partitionTableColumns } from '../../app/static/js/results/result-renderer.js';

test('constant zero metrics remain visible beside each group', () => {
  const result = {columns:['customer','event','rate'],metadata:{},rows:[
    {customer:'A',event:'failed delivery',rate:0},
    {customer:'B',event:'failed delivery',rate:0},
  ]};
  assert.deepEqual(partitionTableColumns(result,result.columns), {
    commonColumns:['event'],detailColumns:['customer','rate'],
  });
  result.metadata.column_metadata=[{name:'rate',role:'metric'}];
  result.rows.forEach((row) => {row.rate='0';});
  assert.ok(partitionTableColumns(result,result.columns).detailColumns.includes('rate'));
});

const plan = { original_question: '분석', event_types: ['failed delivery'], metric: { kind: 'count', unit: 'order' } };
test('core grouping retains nested and multiple metrics, with other fields in details', () => {
  for (const path of ['metric.kind', 'metric.field', 'metrics[0].denominator', 'metrics.1.kind']) assert.equal(cardKeyForBlock({field_path:path}), 'metric');
  assert.equal(cardKeyForBlock({field_path:'date_range'}), 'date_range');
  assert.equal(cardKeyForBlock({field_path:'filters[0].value'}), null);
  assert.equal(cardKeyForBlock({field_path:'limit'}), null);
});
test('incomplete dates, ratios and event comparisons cannot execute', () => {
  for (const extra of [
    {date_range:{mode:'custom',date_from:'2026-10-24'}},
    {date_range:{mode:'relative',relative_days:0}},
    {date_range:{mode:'relative',relative_days:1.5}},
    {metrics:[{kind:'ratio',numerator:'order_id'}]},
    {comparison:'event_vs_event'},
  ]) assert.equal(validatePlanForConfirmation({...plan,...extra}).valid, false);
  assert.equal(validatePlanForConfirmation({...plan,comparison:'event_vs_event',event_types:['a','b']}).valid,true);
});
test('saved revisions retain original reset snapshot; new plans replace it', () => {
  const surface = (revision, days, planId='plan-1') => ({surface_id:'surface', plan_id:planId, revision, surface_type:'plan',components:[],data_model:{analysis_plan:{...plan,date_range:{mode:'relative',relative_days:days}}}});
  installPlanSurface(surface(1,7));
  installPlanSurface(surface(2,30));
  assert.equal(reviewState.initialPlanSnapshot.date_range.relative_days,7);
  assert.equal(reviewState.savedPlanSnapshot.date_range.relative_days,30);
  assert.equal(reviewState.currentSurface.revision,2);
  installPlanSurface(surface(1,90,'plan-2'));
  assert.equal(reviewState.initialPlanSnapshot.date_range.relative_days,90);
});

test('dynamic block labels and defaults are read from AnalysisPlan', async () => {
  const { blockValueLabel } = await import('../../app/static/js/a2ui/plan/plan-renderer.js');
  assert.equal(blockValueLabel({field_path:'date_range'}, {date_range:{mode:'relative',relative_days:30}}), '최근 30일');
  assert.equal(blockValueLabel({field_path:'sort[0].direction',options:[{value:'desc',label:'실패율 높은 순'}]}, {sort:[{field:'metric',direction:'desc'}]}), '실패율 높은 순');
});

test('headline mirror and unit stay synchronized without dropping independent metrics', async () => {
  const { applyLocalPlanEdit, calculationSummary } = await import('../../app/static/js/a2ui/plan/plan-renderer.js');
  const m={kind:'count',field:'order_id',unit:'order',distinct:true};
  const independent={kind:'avg',field:'price',unit:'price'};
  const p={metric:structuredClone(m),metrics:[structuredClone(m),independent]};
  applyLocalPlanEdit(p,'metric.field','customer_id');
  assert.equal(p.metric.unit,'customer');
  assert.deepEqual(p.metrics[0],p.metric);
  assert.deepEqual(p.metrics[1],independent);
  assert.equal(calculationSummary(p),'중복을 제거한 고객 기준');
});

test('metric change derives ratio semantics and dependent grouping without extra input state', async () => {
  const { applyLocalPlanEdit, optionsForBlock } = await import('../../app/static/js/a2ui/plan/plan-renderer.js');
  const d={label:'배송 실패율',field:'order_id',numerator:'failed_delivery_orders',denominator:'shipment_orders',group_by:['customer_id']};
  const catalog={semantic_metrics:{shipment_failure_rate:d},group_by:[{value:'customer_id',label:'고객별'},{value:'product_id',label:'상품별'}]};
  const p={metric:{kind:'count',field:'order_id',unit:'order',distinct:true},metrics:[]};
  p.metrics.push(structuredClone(p.metric));
  applyLocalPlanEdit(p,'metric.kind','ratio',catalog);
  assert.equal(p.metric.semantic_id,'shipment_failure_rate');
  assert.equal(p.metric.numerator,d.numerator);
  assert.deepEqual(p.metrics,[p.metric]);
  const block=optionsForBlock({field_path:'group_by'},p,catalog);
  assert.deepEqual(block.options,[catalog.group_by[0]]);
});

test('unsupported numeric metric cannot be confirmed', () => {
  const catalog={numeric_fields:[],group_by:[],semantic_metrics:{}};
  const p={...plan,metric:{kind:'avg',field:'delivery_duration'}};
  assert.equal(validatePlanForConfirmation(p,[],[],catalog).valid,false);
});

test('metric selector separates count definitions from ratio definitions', async () => {
  const {optionsForBlock} = await import('../../app/static/js/a2ui/plan/plan-renderer.js');
  const catalog={semantic_metrics:{count:{kind:'count',label:'문제 건수'},rate:{kind:'ratio',label:'문제 비율'}}};
  const block={field_path:'metric.semantic_id'};
  assert.deepEqual(optionsForBlock(block,{metric:{kind:'count'}},catalog).options.map(o=>o.value),['count']);
  assert.deepEqual(optionsForBlock(block,{metric:{kind:'ratio'}},catalog).options.map(o=>o.value),['rate']);
});

test('monthly event comparison charts retain both month and event dimensions', async () => {
  const {shouldShowChart,chartRowLabel} = await import('../../app/static/js/results/result-renderer.js');
  const result={columns:['month','event_type','count'],metadata:{result_view:'chart'},rows:[
    {month:'2024-01',event_type:'failed delivery',count:3},
    {month:'2024-01',event_type:'package delivered',count:8},
    {month:'2024-02',event_type:'failed delivery',count:2},
  ]};
  assert.equal(shouldShowChart(result),true);
  assert.equal(chartRowLabel(result,result.rows[0]),'2024-01 · failed delivery');
  assert.notEqual(chartRowLabel(result,result.rows[0]),chartRowLabel(result,result.rows[1]));
});
