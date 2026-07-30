# Parser V2 Gold Validation

## sketch
- primary_evidence_count: 1
- report_assertion_count: 0
- temporal: {'observed_local_date': '2023-09-09', 'documented_local_date': '2023-09-09', 'submitted_local_date': None, 'available_local_date': '2023-09-09', 'available_basis': 'FACE_SKETCH_SIGNED_DATE'}
- ranges: [[1013184.2, 1013184.2]]

## hsp
- primary_evidence_count: 5
- report_assertion_count: 0
- temporal: {'observed_local_date': '2023-09-13', 'documented_local_date': '2023-09-14', 'submitted_local_date': '2023-09-14', 'available_local_date': '2023-09-14', 'available_basis': 'SUBMITTED_TIME_PRIORITY'}
- ranges: [[1013190.2, 1013190.2], [1013190.2, 1013224.0], [1013224.0, 1013238.0], [1013238.0, 1013265.0], [1013265.0, 1013290.2]]

## tsp
- primary_evidence_count: 8
- report_assertion_count: 9
- temporal: {'observed_local_date': '2023-06-02', 'documented_local_date': '2023-06-03', 'submitted_local_date': '2023-06-03', 'available_local_date': '2023-06-03', 'available_basis': 'SUBMITTED_TIME_PRIORITY'}
- ranges: [[1013080.2, 1013080.2], [1013080.2, 1013096.0], [1013096.0, 1013114.0], [1013114.0, 1013120.0], [1013120.0, 1013137.0], [1013137.0, 1013161.0], [1013161.0, 1013182.0], [1013182.0, 1013200.2]]
- conflicts: [{"assertion_id": "593640389447c96b1c9979b7", "document_id": "45c18d05bcf9d4b9cc2eef4b", "assertion_type": "GRADE_SUMMARY", "spatial_scope": {"kind": "INTERVAL", "start_chainage": 1013182.0, "end_chainage": 1013200.2, "raw_expression": "DyK1013+182～DyK1013+200.2", "basis": "tsp_chapter7_grade_summary"}, "raw_text": "DyK1013+182～DyK1013+200.2 建议按Ⅳ级围岩施工", "source_spans": [{"span_id": "d37328614ba5dc5c2ba658ec", "page_number": 10, "extraction_method": "pymupdf_text_layer", "bbox": null, "text_start": 175, "text_end": 694, "raw_text": "7 结论 \n根据伯舒拉岭隧道进口右线的隧道地震预报2D 和3D 成果图，结合掌\n子面地质编录、设计文件、工程和水文地质资料等，对掌子面前方120m 范\n围内隧道围岩的工程地质和水文地质情况进行综合分析及资料解释，得出以\n下结论： \n（1 ）DyK1013+080.2 ～DyK1013+161 段建议按Ⅴ级围岩施工，\nDyK1013+161～DyK1013+182 段建议按Ⅳ级围岩施工，DyK1013+182～\nDyK1013+200.2 段建议按Ⅳ级围岩施工。 \n（2） DyK1013+137～DyK1013+161 段节理裂隙发育密集，岩体破碎-\n极破碎；DyK1013+182～DyK1013+200.2 段岩质软硬不均，节理裂隙发育密\n集，局部泥质填充，岩体破碎-极破碎，该两段围岩整体稳定性较差，存在\n掉块风险。 \n（3）DyK1013+096～DyK1013+114、DyK1013+130～DyK1013+137 段\n掌子面存在线-股状出水；DyK1013+137～DyK1013+161 段掌子面存在线状\n出水；DyK1013+182～DyK1013+200.2 段掌子面存在线-股状出水。该四段\n掌子面存在出水风险。", "normalized_text": "7结论根据伯舒拉岭隧道进口右线的隧道地震预报2D和3D成果图，结合掌子面地质编录、设计文件、工程和水文地质资料等，对掌子面前方120m范围内隧道围岩的工程地质和水文地质情况进行综合分析及资料解释，得出以下结论：（1）DyK1013+080.2~DyK1013+161段建议按Ⅴ级围岩施工，DyK1013+161~DyK1013+182段建议按Ⅳ级围岩施工，DyK1013+182~DyK1013+200.2段建议按Ⅳ级围岩施工。（2）DyK1013+137~DyK1013+161段节理裂隙发育密集，岩体破碎-极破碎；DyK1013+182~DyK1013+200.2段岩质软硬不均，节理裂隙发育密集，局部泥质填充，岩体破碎-极破碎，该两段围岩整体稳定性较差，存在掉块风险。（3）DyK1013+096~DyK1013+114、DyK1013+130~DyK1013+137段掌子面存在线-股状出水；DyK1013+137~DyK1013+161段掌子面存在线状出水；DyK1013+182~DyK1013+200.2段掌子面存在线-股状出水。该四段掌子面存在出水风险。", "source_role": "tsp_chapter7_conclusion"}], "derived_from_evidence_ids": ["ec08ee3255d087536f426912"], "consistency_status": "CONFLICT", "conflict_details": ["table suggested_grade=Ⅴ级; summary suggested_grade=Ⅳ级"]}]
