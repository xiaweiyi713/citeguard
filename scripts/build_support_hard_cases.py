"""Build the first maintainer-reviewed real-source hard-case slice."""

from __future__ import annotations

import json
from pathlib import Path


TRANSFORMER = (
    "The dominant sequence transduction models are based on complex recurrent or convolutional "
    "neural networks in an encoder-decoder configuration. The best performing models also connect "
    "the encoder and decoder through an attention mechanism. We propose a new simple network "
    "architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence "
    "and convolutions entirely. Experiments on two machine translation tasks show these models to be "
    "superior in quality while being more parallelizable and requiring significantly less time to train. "
    "Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task, improving over "
    "the existing best results, including ensembles by over 2 BLEU. On the WMT 2014 English-to-French "
    "translation task, our model establishes a new single-model state-of-the-art BLEU score of 41.8 "
    "after training for 3.5 days on eight GPUs, a small fraction of the training costs of the best "
    "models from the literature. We show that the Transformer generalizes well to other tasks by "
    "applying it successfully to English constituency parsing both with large and limited training data."
)
BERT = (
    "We introduce a new language representation model called BERT, which stands for Bidirectional "
    "Encoder Representations from Transformers. Unlike recent language representation models, BERT is "
    "designed to pre-train deep bidirectional representations from unlabeled text by jointly "
    "conditioning on both left and right context in all layers. As a result, the pre-trained BERT "
    "model can be fine-tuned with just one additional output layer to create state-of-the-art models "
    "for a wide range of tasks, such as question answering and language inference, without substantial "
    "task-specific architecture modifications. BERT is conceptually simple and empirically powerful. "
    "It obtains new state-of-the-art results on eleven natural language processing tasks, including "
    "pushing the GLUE score to 80.5% (7.7% point absolute improvement), MultiNLI accuracy to 86.7% "
    "(4.6% absolute improvement), SQuAD v1.1 question answering Test F1 to 93.2 (1.5 point absolute "
    "improvement) and SQuAD v2.0 Test F1 to 83.1 (5.1 point absolute improvement)."
)
GPT3 = (
    "Recent work has demonstrated substantial gains on many NLP tasks and benchmarks by pre-training "
    "on a large corpus of text followed by fine-tuning on a specific task. While typically "
    "task-agnostic in architecture, this method still requires task-specific fine-tuning datasets of "
    "thousands or tens of thousands of examples. By contrast, humans can generally perform a new "
    "language task from only a few examples or from simple instructions - something which current NLP "
    "systems still largely struggle to do. Here we show that scaling up language models greatly "
    "improves task-agnostic, few-shot performance, sometimes even reaching competitiveness with prior "
    "state-of-the-art fine-tuning approaches. Specifically, we train GPT-3, an autoregressive language "
    "model with 175 billion parameters, 10x more than any previous non-sparse language model, and test "
    "its performance in the few-shot setting. For all tasks, GPT-3 is applied without any gradient "
    "updates or fine-tuning, with tasks and few-shot demonstrations specified purely via text "
    "interaction with the model. GPT-3 achieves strong performance on many NLP datasets, including "
    "translation, question-answering, and cloze tasks, as well as several tasks that require on-the-fly "
    "reasoning or domain adaptation, such as unscrambling words, using a novel word in a sentence, or "
    "performing 3-digit arithmetic. At the same time, we also identify some datasets where GPT-3's "
    "few-shot learning still struggles, as well as some datasets where GPT-3 faces methodological "
    "issues related to training on large web corpora."
)
RESNET = (
    "Deeper neural networks are more difficult to train. We present a residual learning framework to "
    "ease the training of networks that are substantially deeper than those used previously. We "
    "explicitly reformulate the layers as learning residual functions with reference to the layer "
    "inputs, instead of learning unreferenced functions. We provide comprehensive empirical evidence "
    "showing that these residual networks are easier to optimize, and can gain accuracy from "
    "considerably increased depth. On the ImageNet dataset we evaluate residual nets with a depth of "
    "up to 152 layers---8x deeper than VGG nets but still having lower complexity. An ensemble of these "
    "residual nets achieves 3.57% error on the ImageNet test set. This result won the 1st place on the "
    "ILSVRC 2015 classification task. We also present analysis on CIFAR-10 with 100 and 1000 layers. "
    "The depth of representations is of central importance for many visual recognition tasks. Solely "
    "due to our extremely deep representations, we obtain a 28% relative improvement on the COCO object "
    "detection dataset."
)
ALPHAFOLD = (
    "Proteins are essential to life, and understanding their structure can facilitate a mechanistic "
    "understanding of their function. Through an enormous experimental effort, the structures of around "
    "100,000 unique proteins have been determined, but this represents a small fraction of the billions "
    "of known protein sequences. Accurate computational approaches are needed to address this gap. "
    "Despite recent progress, existing methods fall far short of atomic accuracy, especially when no "
    "homologous structure is available. Here we provide the first computational method that can "
    "regularly predict protein structures with atomic accuracy even in cases in which no similar "
    "structure is known. We validated AlphaFold in CASP14, demonstrating accuracy competitive with "
    "experimental structures in a majority of cases and greatly outperforming other methods."
)


def _case(**kwargs):
    payload = {
        "evidence_scope": "abstract",
        "evidence_locator": "abstract",
        "label_source": "maintainer_reviewed",
        "rights_basis": "public_abstract",
        "benchmark_origin": "real_source",
        "writing_context": "literature_review",
    }
    payload.update(kwargs)
    return payload


def build() -> dict:
    papers = {
        "transformer": {
            "paper_id": "arxiv:1706.03762",
            "source_locator": "https://arxiv.org/abs/1706.03762",
            "evidence": TRANSFORMER,
            "split": "train",
            "domain": "computer_science",
        },
        "bert": {
            "paper_id": "arxiv:1810.04805",
            "source_locator": "https://arxiv.org/abs/1810.04805",
            "evidence": BERT,
            "split": "train",
            "domain": "computer_science",
        },
        "gpt3": {
            "paper_id": "arxiv:2005.14165",
            "source_locator": "https://arxiv.org/abs/2005.14165",
            "evidence": GPT3,
            "split": "dev",
            "domain": "computer_science",
        },
        "resnet": {
            "paper_id": "doi:10.1109/cvpr.2016.90",
            "source_locator": "https://doi.org/10.1109/cvpr.2016.90",
            "evidence": RESNET,
            "split": "test",
            "domain": "computer_science",
        },
        "alphafold": {
            "paper_id": "doi:10.1038/s41586-021-03819-2",
            "source_locator": "https://doi.org/10.1038/s41586-021-03819-2",
            "evidence": ALPHAFOLD,
            "split": "test",
            "domain": "biomedicine",
        },
    }
    specs = {
        "transformer": [
            ("direct", "direct_support", "direct_support", "supported", "natural_excerpt", "en",
             "The Transformer is based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
             "Close paraphrase of the abstract's architecture claim."),
            ("related", "hard_negative", "related_not_support", "insufficient_evidence", "maintainer_perturbation", "en",
             "The Transformer paper proves that convolutional sequence models cannot use attention.",
             "Related topic, but the abstract does not claim CNNs cannot use attention."),
            ("causal", "hard_negative", "causal_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "Attention mechanisms caused recurrence to become obsolete for every sequence modeling problem.",
             "Causal/universal overclaim beyond two MT tasks plus parsing."),
            ("scope", "hard_negative", "scope_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "The Transformer outperforms all previous models on every machine translation benchmark.",
             "Abstract reports two WMT 2014 translation tasks, not every benchmark."),
            ("omit", "hard_negative", "condition_omission", "insufficient_evidence", "maintainer_perturbation", "en",
             "The Transformer establishes a new single-model state-of-the-art BLEU score of 41.8.",
             "Omits the English-to-French task and 3.5-day/8-GPU training condition."),
            ("contra", "contradiction", "contradiction", "contradicted", "maintainer_perturbation", "en",
             "The Transformer encoder still depends on recurrent layers.",
             "Abstract says it dispenses with recurrence entirely."),
            ("ft", "full_text_required", "full_text_required", "insufficient_evidence", "maintainer_perturbation", "en",
             "Follow-up tables in the PDF show the same BLEU gains held for a decade.",
             "Abstract cannot support a longitudinal follow-up claim."),
            ("direct-zh", "direct_support", "direct_support", "supported", "natural_excerpt", "zh",
             "Transformer 完全基于注意力机制，不再使用循环和卷积。",
             "Chinese close paraphrase of the architecture claim."),
            ("scope-zh", "hard_negative", "scope_overclaim", "insufficient_evidence", "maintainer_perturbation", "zh",
             "Transformer 在所有机器翻译任务上都优于以往全部方法。",
             "Chinese scope overclaim beyond the two reported translation tasks."),
        ],
        "bert": [
            ("direct", "direct_support", "direct_support", "supported", "natural_excerpt", "en",
             "The pre-trained BERT model can be fine-tuned with just one additional output layer for a wide range of tasks.",
             "Direct abstract statement."),
            ("related", "hard_negative", "related_not_support", "insufficient_evidence", "maintainer_perturbation", "en",
             "BERT shows that unlabeled text is sufficient to replace all labeled downstream datasets.",
             "Related pretraining theme, not supported as a replacement of labeled data."),
            ("causal", "hard_negative", "causal_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "Bidirectional pre-training causes BERT to succeed on every language task without exceptions.",
             "Causal universal overclaim; abstract lists eleven tasks."),
            ("scope", "hard_negative", "scope_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "BERT obtains state-of-the-art results on every natural language processing task.",
             "Abstract reports eleven NLP tasks, not every task."),
            ("omit", "hard_negative", "condition_omission", "insufficient_evidence", "maintainer_perturbation", "en",
             "BERT can create state-of-the-art models without substantial task-specific architecture modifications.",
             "Omits that this follows from fine-tuning a pre-trained model with one output layer."),
            ("contra", "contradiction", "contradiction", "contradicted", "maintainer_perturbation", "en",
             "BERT requires substantial task-specific architecture modifications before it can be used.",
             "Abstract explicitly says without substantial task-specific architecture modifications."),
            ("ft", "full_text_required", "full_text_required", "insufficient_evidence", "maintainer_perturbation", "en",
             "The appendix proves BERT remains best on every GLUE subset after later model releases.",
             "Abstract cannot support later-model comparisons."),
        ],
        "gpt3": [
            ("direct", "direct_support", "direct_support", "supported", "natural_excerpt", "en",
             "Scaling up language models greatly improves task-agnostic, few-shot performance.",
             "Direct abstract statement."),
            ("related", "hard_negative", "related_not_support", "insufficient_evidence", "maintainer_perturbation", "en",
             "GPT-3 shows that web-scale pretraining removes the need to evaluate on any specific dataset.",
             "Related scaling theme; abstract still evaluates many datasets and notes failures."),
            ("causal", "hard_negative", "causal_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "Increasing parameter count causes GPT-3 to solve every few-shot language task.",
             "Causal overclaim; abstract reports datasets where few-shot learning still struggles."),
            ("scope", "hard_negative", "scope_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "GPT-3 achieves state-of-the-art performance on every language task without exceptions.",
             "Abstract says strong performance on many datasets and explicitly notes struggles."),
            ("omit", "hard_negative", "condition_omission", "insufficient_evidence", "maintainer_perturbation", "en",
             "GPT-3 is applied to all tasks and achieves strong performance.",
             "Omits the few-shot, no-gradient-update setting and the datasets where it struggles."),
            ("contra", "contradiction", "contradiction", "contradicted", "maintainer_perturbation", "en",
             "GPT-3 few-shot learning does not struggle on any evaluated dataset.",
             "Abstract identifies datasets where few-shot learning still struggles."),
            ("ft", "full_text_required", "full_text_required", "insufficient_evidence", "maintainer_perturbation", "en",
             "Section 3 tables show GPT-3 matches fine-tuned SOTA on every SuperGLUE task.",
             "Abstract-level evidence is insufficient for that table-level claim."),
        ],
        "resnet": [
            ("direct", "direct_support", "direct_support", "supported", "natural_excerpt", "en",
             "Residual networks are easier to optimize and can gain accuracy from considerably increased depth.",
             "Direct abstract statement."),
            ("related", "hard_negative", "related_not_support", "insufficient_evidence", "maintainer_perturbation", "en",
             "Residual connections prove that network width is more important than depth.",
             "Related optimization topic; abstract emphasizes depth, not that width dominates."),
            ("causal", "hard_negative", "causal_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "Residual connections cause any deep network to win every vision benchmark.",
             "Causal universal overclaim beyond ImageNet/CIFAR/COCO results."),
            ("scope", "hard_negative", "scope_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "Residual networks are the easiest models to train in every application domain.",
             "Abstract evidence is vision-centric, not every domain."),
            ("omit", "hard_negative", "condition_omission", "insufficient_evidence", "maintainer_perturbation", "en",
             "An ensemble of residual nets achieves 3.57% error.",
             "Omits that this is the ImageNet test set / ILSVRC 2015 classification setting."),
            ("contra", "contradiction", "contradiction", "contradicted", "maintainer_perturbation", "en",
             "Deeper residual networks cannot gain accuracy from increased depth.",
             "Abstract says they can gain accuracy from considerably increased depth."),
            ("ft", "full_text_required", "full_text_required", "insufficient_evidence", "maintainer_perturbation", "en",
             "Layer-wise ablation in the PDF shows 1000-layer CIFAR models beat every later architecture.",
             "Abstract cannot support later-architecture comparisons."),
            ("direct-zh", "direct_support", "direct_support", "supported", "natural_excerpt", "zh",
             "残差网络更易于优化，并且能从显著增加的深度中获得精度。",
             "Chinese close paraphrase of the residual-learning claim."),
            ("scope-zh", "hard_negative", "scope_overclaim", "insufficient_evidence", "maintainer_perturbation", "zh",
             "残差网络在所有应用领域都是最容易训练的模型。",
             "Chinese scope overclaim beyond the reported vision tasks."),
        ],
        "alphafold": [
            ("direct", "direct_support", "direct_support", "supported", "natural_excerpt", "en",
             "AlphaFold can regularly predict protein structures with atomic accuracy even when no similar structure is known.",
             "Direct abstract statement."),
            ("related", "hard_negative", "related_not_support", "insufficient_evidence", "maintainer_perturbation", "en",
             "AlphaFold shows that experimental protein structure determination is no longer necessary.",
             "Related structure-prediction theme; abstract still discusses experimental structures and CASP."),
            ("causal", "hard_negative", "causal_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "Incorporating physical knowledge into the network causes AlphaFold to fold every protein perfectly.",
             "Causal universal overclaim; validation is CASP14, majority of cases."),
            ("scope", "hard_negative", "scope_overclaim", "insufficient_evidence", "maintainer_perturbation", "en",
             "AlphaFold determines the structure of every known protein with experimental certainty.",
             "Abstract claims regular atomic accuracy on CASP14, not every protein with experimental certainty."),
            ("omit", "hard_negative", "condition_omission", "insufficient_evidence", "maintainer_perturbation", "en",
             "AlphaFold demonstrates accuracy competitive with experimental structures.",
             "Omits CASP14 and 'a majority of cases'."),
            ("contra", "contradiction", "contradiction", "contradicted", "maintainer_perturbation", "en",
             "Existing methods already achieve atomic accuracy whenever no homologous structure is available.",
             "Abstract says existing methods fall far short of atomic accuracy in that setting."),
            ("ft", "full_text_required", "full_text_required", "insufficient_evidence", "maintainer_perturbation", "en",
             "Supplementary figures show AlphaFold recovers every CASP14 target to experimental uncertainty.",
             "Abstract does not support a supplementary every-target claim."),
        ],
    }
    cases = []
    for paper_key, rows in specs.items():
        meta = papers[paper_key]
        for suffix, case_type, family, gold, origin, lang, claim, notes in rows:
            cases.append(
                _case(
                    **meta,
                    id=f"hc-{paper_key}-{suffix}",
                    case_type=case_type,
                    error_family=family,
                    gold=gold,
                    origin=origin,
                    lang=lang,
                    claim=claim,
                    label_notes=notes,
                )
            )
    set_cases = [
        {
            "id": "hc-set-nlp-overclaim",
            "claim": "Transformer and BERT together prove that neural pretraining solves every NLP task.",
            "citation_verdicts": ["verified", "verified"],
            "gold": "insufficient_evidence",
            "lang": "en",
            "label_source": "maintainer_reviewed",
            "label_notes": "Two related papers do not add up to a universal NLP result.",
            "case_type": "weak_set_boundary",
            "error_family": "multi_citation_aggregation",
            "split": "train",
            "paper_ids": ["arxiv:1706.03762", "arxiv:1810.04805"],
            "origin": "maintainer_perturbation",
            "benchmark_origin": "real_source",
        },
        {
            "id": "hc-set-vision-bio-overclaim",
            "claim": "ResNet and AlphaFold together show deep learning is universally accurate across vision and biology.",
            "citation_verdicts": ["verified", "verified"],
            "gold": "insufficient_evidence",
            "lang": "en",
            "label_source": "maintainer_reviewed",
            "label_notes": "Combining two domain-specific results does not justify a universal accuracy claim.",
            "case_type": "weak_set_boundary",
            "error_family": "multi_citation_aggregation",
            "split": "test",
            "paper_ids": ["doi:10.1109/cvpr.2016.90", "doi:10.1038/s41586-021-03819-2"],
            "origin": "maintainer_perturbation",
            "benchmark_origin": "real_source",
        },
    ]
    return {
        "schema_version": 1,
        "dataset_type": "real_source_hard_cases",
        "campaign_id": "citeguard-hard-cases-v1",
        "label_policy": {
            "label_source": "maintainer_reviewed",
            "annotator_count": 1,
            "notes": (
                "First maintainer-reviewed real-source slice over public abstracts. "
                "Natural excerpts and maintainer perturbations are labeled separately. "
                "This is not dual-annotated and does not meet the 250-case campaign quota."
            ),
        },
        "cases": cases,
        "set_cases": set_cases,
    }


def main() -> None:
    path = Path("data/eval/support_hard_cases_v1.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path} cases={len(data['cases'])} set_cases={len(data['set_cases'])}")


if __name__ == "__main__":
    main()
