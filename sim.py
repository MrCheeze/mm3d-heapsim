# ported from Leoetlino's original MM3D heapsim code

import math

Flag_IsRefCounted = 1 << 0
Flag_PreventReuse = 1 << 1
Flag_FreeBlockOnRefCountZero = 1 << 3

class Allocator:
    def __init__(self):

        self.dummy_block = AllocatorBlock(0xDEADBEEF)
        self.dummy_block.next_free_l = 0x8010000
        self.dummy_block.next_free_s = 0x8010000
        self.dummy_block.refcounted_next = self.dummy_block.addr
        self.dummy_block.refcounted_prev = self.dummy_block.addr

        initial_block = AllocatorBlock(0x8010000)
        initial_block.size = 0x1897000
        initial_block.next_free_l = 0xDEADBEEF
        initial_block.next_free_s = 0xDEADBEEF
        initial_block.prev = 0x8010000
        initial_block.next = 0x8010000
        
        self.ram = {0xDEADBEEF: self.dummy_block, 0x8010000: initial_block}

    def alloc(self, size, name):
        ptr = 0;
        while True:
            ptr = self.allocSmall(size) if 0x800 > size else self.allocLarge(size)
            if ptr:
                break
            if self.freeUnusedRefCountedBlock(size):
                return ptr;

        block = self.ram[ptr]
        block.next_free_s = 0
        block.next_free_l = 0
        block.name = name
        block.magic = 0x12345678ABCDEF86
        block.alloc_ticks = -1

        return ptr

    def allocLarge(self, size):
        block = self.ram[self.dummy_block.next_free_l]
        alloc_size = math.ceil(size / 0x10) * 0x10 + 0x40
        while True:
            if block.size - alloc_size >= 0:
                break

            block = self.ram[block.next_free_l]
            if block.addr == self.dummy_block.addr:
                return 0
            
        new_free_size = block.size - alloc_size
        if block.size == alloc_size or new_free_size <= 0x40:
            self.ram[block.next_free_s].next_free_l = block.next_free_l
            self.ram[block.next_free_l].next_free_s = block.next_free_s
            block.id = 0
            block.flags = 0
            block.ref_count = 1
            block.size = -block.size
            return block.addr

        new_block = AllocatorBlock(block.addr + alloc_size)
        self.ram[new_block.addr] = new_block
        self.ram[block.next_free_s].next_free_l = block.next_free_l
        self.ram[block.next_free_l].next_free_s = block.next_free_s
        block.id = 0
        block.flags = 0
        block.ref_count = 1
        block.size = -alloc_size

        new_block.id = 0
        new_block.flags = 0
        new_block.ref_count = 1
        new_block.prev = block.addr
        new_block.size = new_free_size
        
        self.ram[block.next].prev = new_block.addr
        new_block.next = block.next
        block.next = new_block.addr

        self.updateFreeLists(new_block)

        return block.addr

    def updateFreeLists(self, block):
        free_block = self.ram[block.prev]
        while free_block.size <= 0:
            free_block = self.ram[free_block.prev]
        if free_block.addr == block.addr:
            self.ram[self.dummy_block.next_free_s].next_free_l = block.addr
            block.next_free_l = self.dummy_block.addr
            block.next_free_s = self.dummy_block.next_free_s
            self.dummy_block.next_free_s = block.addr
        else:
            self.ram[free_block.next_free_l].next_free_s = block.addr
            block.next_free_s = free_block.addr
            block.next_free_l = free_block.next_free_l
            free_block.next_free_l = block.addr


    def allocSmall(self, size):
        block = self.ram[self.dummy_block.next_free_s]
        alloc_size = math.ceil(size / 0x10) * 0x10 + 0x40
        while True:
            if block.size - alloc_size >= 0:
                break

            block = self.ram[block.next_free_s]
            if block.addr == self.dummy_block.addr:
                return 0
            
        new_free_size = block.size - alloc_size
        if block.size == alloc_size or new_free_size <= 0x40:
            self.ram[block.next_free_s].next_free_l = block.next_free_l
            self.ram[block.next_free_l].next_free_s = block.next_free_s
            block.id = 0
            block.flags = 0
            block.ref_count = 1
            block.size = -block.size
            return block.addr

        new_block = AllocatorBlock(block.addr + new_free_size)
        self.ram[new_block.addr] = new_block

        new_block.id = 0
        new_block.flags = 0
        new_block.ref_count = 1
        new_block.prev = block.addr
        new_block.size = -alloc_size
        block.size = new_free_size
        
        self.ram[block.next].prev = new_block.addr
        new_block.next = block.next
        block.next = new_block.addr

        return new_block.addr

    def free(self, ptr):
        if not ptr:
            return

        block = self.ram[ptr-0x40]

        if block.flags & Flag_IsRefCounted:
            if block.ref_count != 0:
                block.ref_count -= 1

                if (block.ref_count == 0 and
                    block.flags & Flag_FreeBlockOnRefCountZero):
                    self.ram[block.refcounted_next].refcounted_prev = block.refcounted_prev
                    self.ram[block.refcounted_prev].refcounted_next = block.refcounted_next
                    block.refcounted_next = 0
                    block.refcounted_prev = 0
                    self.doFree(ptr)
                
        else:
            self.doFree(ptr)

    def doFree(self, ptr):
        block = self.ram[ptr-0x40]

        block.name = ''
        block.size = -block.size
        self.updateFreeLists(block)
        self.tryToMergeBlock(block)

    def tryToMergeBlock(self, block):
        def merge_into(target, other):
            target.size += other.size
            self.ram[other.next_free_s].next_free_l = other.next_free_l
            self.ram[other.next_free_l].next_free_s = other.next_free_s

            self.ram[other.prev].next = other.next
            self.ram[other.next].prev = other.prev

            del self.ram[other.addr]

        next_block = self.ram[block.next]
        if next_block.size > 0 and block.addr + block.size == next_block.addr:
            merge_into(block, next_block)

        prev_block = self.ram[block.prev]
        if prev_block.size > 0 and block.addr - prev_block.size == prev_block.addr:
            merge_into(prev_block, block)

        return block

    def allocRefCounted(self, alloc_id, size):
        ptr = 0
        while True:
            ptr = self.allocLarge(size)
            if ptr:
                break
            if not self.freeUnusedRefCountedBlock(size):
                return ptr

        block = self.ram[ptr]
        block.id = alloc_id
        block.flags = Flag_IsRefCounted
        block.name = 'REF_COUNTED'
        block.alloc_ticks = -1

        self.ram[self.dummy_block.refcounted_next].refcounted_prev = block.addr
        block.refcounted_next = self.dummy_block.refcounted_next
        block.refcounted_prev = self.dummy_block.addr
        self.dummy_block.refcounted_next = block.addr

        return ptr

    def validate_integrity(self):
        total_size = 0
        for addr in self.ram:

            if addr == self.dummy_block.addr:
                continue
            
            node = self.ram[addr]
            total_size += abs(node.size)
            assert self.ram[node.next].prev==node.addr
            assert self.ram[node.prev].next==node.addr

        assert total_size == 0x1897000
    
    def __repr__(self):
        return '\n'.join(repr(self.ram[addr]) for addr in sorted(self.ram))

class AllocatorBlock:
    def __init__(self, addr):
        self.addr = addr
        self.name = ''
        self.size = 0

    def __repr__(self):
        return '%08X %08X %s %s'%(self.addr, abs(self.size), 'Free' if self.size > 0 else 'Used', self.name)
    
allocator = Allocator()
last_returned_addr = 0

for line in open('citra_log_deku_palace.txt'):
    
    line_split = line.split()

    if ' ALLOC ' in line:
        alloc_size = int(line_split[-2], base=16)
        alloc_name = line_split[-1]
        last_returned_addr = allocator.alloc(alloc_size, alloc_name)
    elif ' ALLOC_RESULT ' in line:
        expected_addr = int(line_split[-3], base=16) - 0x40
        expected_size = int(line_split[-2], base=16)
        expected_name = line_split[-1]
        assert last_returned_addr == expected_addr
        assert expected_addr in allocator.ram
        assert allocator.ram[expected_addr].size == -expected_size
        assert allocator.ram[expected_addr].name == expected_name
    elif ' FREE ' in line:
        free_addr = int(line_split[-1], base=16)
        allocator.free(free_addr)
    elif 'Project Restoration initialised' in line:
        pass
    elif ' ALLOC_REF ' in line:
        alloc_id = int(line_split[-1], base=16)
        alloc_size = int(line_split[-1], base=16)
        last_returned_addr = allocator.allocRefCounted(alloc_id, alloc_size)
    elif ' ALLOC_REF_RESULT ' in line:
        expected_addr = int(line_split[-3], base=16) - 0x40
        expected_size = int(line_split[-2], base=16)
        expected_unk = int(line_split[-1])
        assert last_returned_addr == expected_addr
        assert expected_addr in allocator.ram
        assert allocator.ram[expected_addr].size == -expected_size
        assert allocator.ram[expected_addr].name == 'REF_COUNTED'
        assert allocator.ram[expected_addr].ref_count == expected_unk
        assert allocator.ram[expected_addr].flags == expected_unk
    elif 'statue changed' in line:
        expected_statue_addr = int(line_split[-1], base=16) - 0x40
        if expected_statue_addr > 0:
            assert allocator.ram[expected_statue_addr].size == -0x2d0
            assert allocator.ram[expected_statue_addr].name == 'C:\\Jenkins\\workspace\\joker\\prog\\game\\sources\\original\\z_actor.cpp(10836)'
    else:
        print(line_split)
        1/0

allocator.validate_integrity()