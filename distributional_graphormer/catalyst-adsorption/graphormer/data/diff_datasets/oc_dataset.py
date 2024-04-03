from .diff_dataset import CrossDockedDM, CrossDockedDataset, CrossDockedRawDataset
from .diff_dataset import crossdocked_batch_collater

from ..collator import (
    pad_1d_unsqueeze,
    pad_2d_unsqueeze,
    pad_all_poses_unsqueeze,
    pad_pos_unsqueeze,
    pad_3d_unsqueeze,
    pad_attn_bias_unsqueeze,
    pad_spatial_pos_unsqueeze,
)

import torch

class OCRawDataset(CrossDockedRawDataset):
    def __init__(self, path, file_list, split, subdir="full"):
        super().__init__(path, file_list, subdir)
        self.subdir = subdir
        self.split = split

class OCKDEEvalDatasetDM(CrossDockedDM):
    def get_split(self, split):
        if split not in self.split_lut:
            split_list_lines = open(self.path + f"/{split}.list", "r").readlines()
            split_list = self.process_file_list(split_list_lines)
            if split.endswith("-all-poses") or split.find("-all-poses.") != -1:
                self.split_lut[split] = OCRawDataset(self.path, split_list, split, "all-poses")
            elif split.startswith("density") or split.startswith("grid-") or split == "train-100":
                self.split_lut[split] = OCRawDataset(self.path, split_list, split, split)
            else:
                self.split_lut[split] = OCRawDataset(self.path, split_list, split, "all")
        return self.split_lut[split]

class OCKDEEvalDataset(CrossDockedDataset):
    def collater(self, samples):
        if self.raw_dataset.split.find("all-poses") != -1:
            return oc_batch_collater(samples, has_all_poses=True)
        elif self.raw_dataset.split.startswith("density") or self.raw_dataset.split.startswith("grid"):
            return oc_batch_collater(samples, has_index_ij=True)
        else:
            return oc_batch_collater(samples, has_all_poses=False)

def oc_batch_collater(
    items, max_node=512, multi_hop_max_dist=20, spatial_pos_max=20, has_all_poses=False, has_index_ij=False,
):
    items = [item for item in items if item is not None and item.x.size(0) <= max_node]
    items = [
        (
            item.attn_bias,
            item.spatial_pos,
            item.in_degree,
            item.x,
            torch.cat([pos.unsqueeze(0) for pos in item.all_poses], axis=0) if has_all_poses else None,
            item.offsets if has_all_poses else None,
            item.pos,
            item.init_pos,
            item.edge_input[:, :, :multi_hop_max_dist, :],
            item.num_node,
            item.tags,
            item.natoms,
            item.cell,
            item.atomic_numbers,
            item.num_moveable if (has_all_poses or has_index_ij) else None,
            item.sid,
            item.index_i if has_index_ij else None,
            item.index_j if has_index_ij else None,
        )
        for item in items
    ]
    (
        attn_biases,
        spatial_poses,
        in_degrees,
        xs,
        all_poseses,
        offsetss,
        poses,
        init_poses,
        edge_inputs,
        num_node_tuples,
        tagss,
        natomss,
        cells,
        atomic_numberss,
        num_moveables,
        sids,
        index_is,
        index_js,
    ) = zip(*items)

    if has_all_poses:
        offsets = offsetss[0]
        cur_base = offsets[-1]
        num_groups = [len(offsets) - 1]
        for i in range(1, len(items)):
            offsets = torch.cat([offsets, offsetss[i][1:] + cur_base], dim=0)
            cur_base += offsetss[i][-1]
            num_groups.append(len(offsetss[i]) - 1)
        num_groups = torch.tensor(num_groups)
        num_moveable = torch.tensor([num_moveable for num_moveable in num_moveables])
    elif has_index_ij:
        num_moveable = torch.tensor([num_moveable for num_moveable in num_moveables])
        offsets = None
        num_groups = None
    else:
        offsets = None
        num_moveable = None
        num_groups = None

    for idx, _ in enumerate(attn_biases):
        attn_biases[idx][1:, 1:][(spatial_poses[idx] >= spatial_pos_max) & (spatial_poses[idx] != 511)] = 0.0
    max_node_num = max(i.size(0) for i in xs)
    max_dist = max(i.size(-2) for i in edge_inputs)
    x = torch.cat([pad_2d_unsqueeze(i, max_node_num) for i in xs])

    if not has_all_poses:
        all_poses = None
    else:
        all_poses = torch.cat(
            [pad_all_poses_unsqueeze(i, max_node_num) for i in all_poseses] if all_poseses is not None else None
        )  # workaround for avoid auto adding 1 to pos
    pos = torch.cat(
        [pad_pos_unsqueeze(i, max_node_num) for i in poses]
    )
    init_pos = torch.cat(
        [pad_pos_unsqueeze(i, max_node_num) for i in init_poses]
    )
    edge_input = torch.cat(
        [pad_3d_unsqueeze(i, max_node_num, max_node_num, max_dist) for i in edge_inputs]
    )
    attn_bias = torch.cat(
        [pad_attn_bias_unsqueeze(i, max_node_num + 1) for i in attn_biases]
    )
    spatial_pos = torch.cat(
        [pad_spatial_pos_unsqueeze(i, max_node_num) for i in spatial_poses]
    )
    sid = torch.tensor([sid for sid in sids], dtype=torch.long)
    index_i = torch.tensor([index_i for index_i in index_is], dtype=torch.long) if has_index_ij else None
    index_j = torch.tensor([index_j for index_j in index_js], dtype=torch.long) if has_index_ij else None
    in_degree = torch.cat([pad_1d_unsqueeze(i, max_node_num) for i in in_degrees])

    lnode = torch.tensor([i[0] for i in num_node_tuples])
    pnode = torch.tensor([i[1] for i in num_node_tuples])
    allnode = torch.tensor([i[0] + i[1] for i in num_node_tuples])

    tags = torch.cat(
        [pad_1d_unsqueeze(i, max_node_num) for i in tagss]
    )

    natoms = torch.tensor(list(natomss))
    cell = torch.cat([i for i in cells], axis=0)
    atomic_numbers = torch.cat([i for i in atomic_numberss], axis=0)

    ret = dict(
        attn_bias=attn_bias,
        spatial_pos=spatial_pos,
        in_degree=in_degree,
        out_degree=in_degree,  # for undirected graph
        x=x,
        all_poses=all_poses,
        pos=pos,
        init_pos=init_pos,
        edge_input=edge_input,
        lnode=lnode,
        pnode=pnode,
        allnode=allnode,
        tags=tags,
        natoms=natoms,
        cell=cell,
        atomic_numbers = atomic_numbers,
        offsets=offsets,
        num_moveable=num_moveable,
        num_groups=num_groups,
        sid=sid,
        index_i=index_i,
        index_j=index_j,
    )

    # remove none items
    ret = {k: v for k, v in ret.items() if v is not None}

    return ret


def build_oc_kde_dm(data_path):
    return OCKDEEvalDatasetDM(data_path)


def build_oc_kde_dataset(raw_dataset):
    return OCKDEEvalDataset(raw_dataset)
